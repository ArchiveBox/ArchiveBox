import json
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import Http404, HttpRequest, HttpResponse, QueryDict
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.utils.html import format_html
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.generic import FormView

from archivebox.config import VERSION
from archivebox.config.common import (
    get_config,
    get_request_config,
    redact_sensitive_config,
)
from archivebox.core.forms import AddLinkForm
from archivebox.core.models import Snapshot
from archivebox.core.permissions import (
    PERMISSIONS_PUBLIC,
    direct_snapshots_queryset,
    filter_personas_by_permissions,
)
from archivebox.core.routes_util import (
    build_admin_url,
    build_web_url,
    get_admin_host,
    get_web_host,
    host_matches,
)
from archivebox.crawls.models import Crawl
from archivebox.misc.util import (
    sanitize_html_text,
    urldecode,
    validate_url,
)
from archivebox.plugins.forms import get_plugin_config_binary_urls

from .replay import SnapshotView


@method_decorator(csrf_exempt, name="dispatch")
class AddView(UserPassesTestMixin, FormView):
    template_name = "add.html"
    form_class = AddLinkForm

    def get_initial(self):
        """Prefill the AddLinkForm with the 'url' GET parameter"""
        if self.request.method == "GET":
            url = self.request.GET.get("url", None)
            if url:
                return {"url": url if "://" in url else f"https://{url}"}

        return super().get_initial()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def test_func(self):
        return get_request_config(self.request).PUBLIC_ADD_VIEW or self.request.user.is_authenticated

    def post(self, request: HttpRequest, *args: object, **kwargs: object):
        if request.user.is_authenticated:
            return csrf_protect(super().post)(request, *args, **kwargs)
        return super().post(request, *args, **kwargs)

    def _can_override_crawl_config(self) -> bool:
        user = self.request.user
        return bool(user.is_authenticated and user.is_active and user.is_superuser)

    def _get_custom_config_overrides(self, form: AddLinkForm) -> dict:
        custom_config = form.cleaned_data.get("config") or {}

        if not isinstance(custom_config, dict):
            return {}

        if not self._can_override_crawl_config():
            return {}

        return {str(key): value for key, value in custom_config.items() if not str(key).endswith("_BINARY")}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request_config = get_request_config(self.request, resolve_plugins=True)
        required_search_plugin = f"search_backend_{request_config.SEARCH_BACKEND_ENGINE}".strip()
        can_override_crawl_config = self._can_override_crawl_config()
        public_persona_config_keys = {
            "CRAWL_MAX_CONCURRENT_SNAPSHOTS",
            "DELETE_AFTER",
            "ONLY_NEW",
            "PERMISSIONS",
            "TIMEOUT",
        }
        persona_queryset = context["form"].fields["persona"].queryset
        if not can_override_crawl_config:
            persona_queryset = filter_personas_by_permissions(persona_queryset, {PERMISSIONS_PUBLIC})
        persona_config_map = {}
        for persona in persona_queryset.order_by("name"):
            effective_config = get_config(persona=persona)
            effective_config_redacted = redact_sensitive_config(effective_config.model_dump(mode="json"))
            if can_override_crawl_config:
                raw_config = redact_sensitive_config(persona.config or {})
                effective_config_json = effective_config_redacted
                binary_urls = get_plugin_config_binary_urls(effective_config)
            else:
                raw_config = {}
                effective_config_json = {key: effective_config_redacted.get(key) for key in public_persona_config_keys}
                binary_urls = {}
            persona_config_map[persona.name] = {
                "config": raw_config,
                "effective_config": effective_config_json,
                "binary_urls": binary_urls,
            }
        recent_personas = list(persona_queryset.order_by("-created_at", "name")[:5])
        return {
            **context,
            "title": "Create Crawl",
            # We can't just call request.build_absolute_uri in the template, because it would include query parameters
            "absolute_add_path": self.request.build_absolute_uri(self.request.path),
            "web_base_url": build_web_url("", request=self.request),
            "VERSION": VERSION,
            "FOOTER_INFO": request_config.FOOTER_INFO,
            "required_search_plugin": required_search_plugin,
            "persona_config_map_json": json.dumps(persona_config_map, sort_keys=True, default=str),
            "recent_personas": recent_personas,
            "can_override_crawl_config": can_override_crawl_config,
            "stdout": "",
        }

    def _create_crawl_from_form(self, form, *, created_by_id=None) -> Crawl:
        from archivebox.cli.archivebox_add import add

        urls_input = form.cleaned_data["url"]
        urls = urls_input
        submitted_lines = [line.strip() for line in urls_input.splitlines() if line.strip()]
        if len(submitted_lines) == 1:
            try:
                # A lone URL pasted into /add/ is the same user-facing input as
                # `archivebox add https://...`: queue that URL directly so a
                # narrow plugin selection like `wget` can archive it without
                # also needing parser plugins. Multi-line or formatted text
                # remains verbatim import content for the internal parser root.
                urls = [validate_url(submitted_lines[0])]
            except ValueError:
                pass
        print(f"[+] Adding URL: {urls_input}")

        # Extract all form fields
        tag = form.cleaned_data["tag"]
        depth = int(form.cleaned_data["depth"])
        max_urls = int(form.cleaned_data.get("max_urls") or 0)
        crawl_max_size = int(form.cleaned_data.get("crawl_max_size") or 0)
        crawl_timeout = int(form.cleaned_data.get("crawl_timeout") or 0)
        timeout = form.cleaned_data.get("timeout")
        snapshot_max_size = int(form.cleaned_data.get("snapshot_max_size") or 0)
        delete_after = str(form.cleaned_data.get("delete_after") or "0").strip() or "0"
        crawl_max_concurrent_snapshots = int(form.cleaned_data["crawl_max_concurrent_snapshots"])
        permissions = str(form.cleaned_data.get("permissions") or "public").strip().lower()
        can_override_crawl_config = self._can_override_crawl_config()
        plugins = ",".join(form.cleaned_data.get("plugins", [])) if can_override_crawl_config else ""
        schedule = form.cleaned_data.get("schedule", "").strip() if can_override_crawl_config else ""
        persona = form.cleaned_data.get("persona")
        start_paused = form.cleaned_data.get("start_paused", False) if can_override_crawl_config else False
        notes = form.cleaned_data.get("notes", "")
        url_filters = form.cleaned_data.get("url_filters") or {}
        plugin_config = form.cleaned_data.get("plugin_config") or {}
        if not isinstance(plugin_config, dict):
            plugin_config = {}
        if not can_override_crawl_config:
            plugin_config = {}
        custom_config = self._get_custom_config_overrides(form)
        custom_config.pop("DEFAULT_PERSONA", None)
        custom_config.pop("PERMISSIONS", None)
        if persona:
            persona.ensure_dirs()

        if created_by_id is None:
            if self.request.user.is_authenticated:
                created_by_id = self.request.user.pk
            else:
                from archivebox.base_models.models import get_or_create_system_user_pk

                created_by_id = get_or_create_system_user_pk()

        config = {}
        effective_config = get_config(persona=persona) if persona else get_config()
        if delete_after != str(effective_config.DELETE_AFTER):
            config["DELETE_AFTER"] = delete_after
        if timeout is not None and int(timeout) != int(effective_config.TIMEOUT):
            config["TIMEOUT"] = int(timeout)
        if permissions:
            config["PERMISSIONS"] = permissions

        config.update(plugin_config)
        config.update(custom_config)
        if bool(url_filters.get("only_new")) != bool(effective_config.ONLY_NEW):
            config["ONLY_NEW"] = bool(url_filters.get("only_new"))
        crawl, _snapshots = add(
            urls=urls,
            depth=depth,
            max_urls=max_urls,
            crawl_max_size=crawl_max_size,
            crawl_timeout=crawl_timeout,
            snapshot_max_size=snapshot_max_size,
            crawl_max_concurrent_snapshots=crawl_max_concurrent_snapshots,
            tag=tag,
            url_allowlist=url_filters.get("allowlist") or "",
            url_denylist=url_filters.get("denylist") or "",
            plugins=plugins,
            persona=persona.name if persona else "Default",
            bg=True,
            created_by_id=created_by_id,
            config=config,
        )
        if notes:
            crawl.safe_update({"notes": sanitize_html_text(notes)}, refresh=False)
        if permissions and crawl.config.get("PERMISSIONS") != permissions:
            next_config = {**crawl.config, "PERMISSIONS": permissions}
            crawl.safe_update({"config": next_config}, refresh=True)
        if start_paused:
            crawl.pause()

        # 3. create a CrawlSchedule if schedule is provided
        if schedule:
            from archivebox.crawls.models import CrawlSchedule

            crawl_schedule = CrawlSchedule.objects.create(
                template=crawl,
                schedule=schedule,
                is_enabled=True,
                config=config,
                label=crawl.label,
                notes=f"Auto-created from add page. {notes}".strip(),
                created_by_id=created_by_id,
            )
            crawl.schedule = crawl_schedule
            crawl.safe_update({"schedule": crawl_schedule}, refresh=False)

        return crawl

    def form_valid(self, form):
        crawl = self._create_crawl_from_form(form)

        urls = form.cleaned_data["url"]
        schedule = form.cleaned_data.get("schedule", "").strip()
        rough_url_count = len([url for url in urls.splitlines() if url.strip()])

        schedule_msg = ""
        if schedule and crawl.schedule_id:
            schedule_msg = format_html(" and <a href='{}'>scheduled to repeat {}</a>", crawl.schedule.admin_change_url, schedule)

        messages.success(
            self.request,
            format_html(
                "Created crawl with {} starting URL(s){}. Snapshots will be created and archived in the background. <a href='{}'>View Crawl →</a>",
                rough_url_count,
                schedule_msg,
                crawl.admin_change_url,
            ),
        )

        # Orchestrator (managed by supervisord) will pick up the queued crawl
        return redirect(crawl.admin_change_url)


class WebAddView(AddView):
    def _latest_snapshot_for_url(self, requested_url: str):
        return (
            direct_snapshots_queryset(
                self.request,
                SnapshotView.find_snapshots_for_url(requested_url),
            )
            .order_by("-bookmarked_at", "-created_at", "-timestamp")
            .first()
        )

    def _normalize_add_url(self, requested_url: str) -> str:
        if requested_url.startswith(("http://", "https://")):
            return requested_url
        return f"https://{requested_url}"

    def dispatch(self, request, *args, **kwargs):
        requested_url = urldecode(kwargs.get("url", "") or "")
        if requested_url:
            snapshot = self._latest_snapshot_for_url(requested_url)
            if snapshot:
                return redirect(f"/{snapshot.url_path}")

        request_host = (request.get_host() or "").lower()
        request_config = get_request_config(request)
        web_host = get_web_host(config=request_config, request=request)
        admin_host = get_admin_host(config=request_config, request=request)
        is_web_host = host_matches(request_host, web_host)
        is_admin_host = host_matches(request_host, admin_host)
        if request.user.is_authenticated and not request_config.PUBLIC_ADD_VIEW and is_web_host and not is_admin_host:
            return redirect(build_admin_url(request.get_full_path(), request=request))

        if not self.test_func():
            if is_web_host and not is_admin_host:
                return redirect(build_admin_url(request.get_full_path(), request=request))
            if is_admin_host:
                next_url = quote(request.get_full_path(), safe="/:?=&")
                return redirect(f"{build_admin_url('/admin/login/', request=request)}?next={next_url}")
            return HttpResponse(
                format_html(
                    (
                        "<center><br/><br/><br/>"
                        "No Snapshots match the given url: <code>{}</code><br/><br/><br/>"
                        'Return to the <a href="/" target="_top">Main Index</a>'
                        "</center>"
                    ),
                    requested_url or "",
                ),
                content_type="text/html",
                status=404,
            )

        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, *args: object, **kwargs: object):
        requested_url = urldecode(str(kwargs.get("url") or (args[0] if args else "")))
        if not requested_url:
            raise Http404

        snapshot = self._latest_snapshot_for_url(requested_url)
        if snapshot:
            return redirect(f"/{snapshot.url_path}")

        add_url = self._normalize_add_url(requested_url)
        assert self.form_class is not None
        defaults_form = self.form_class()
        form_data = QueryDict(mutable=True)
        form_data.update(
            {
                "url": add_url,
                "depth": defaults_form.fields["depth"].initial or "0",
                "max_urls": defaults_form.fields["max_urls"].initial or 0,
                "crawl_max_size": defaults_form.fields["crawl_max_size"].initial or "0",
                "crawl_timeout": defaults_form.fields["crawl_timeout"].initial or 0,
                "timeout": defaults_form.fields["timeout"].initial or 0,
                "snapshot_max_size": defaults_form.fields["snapshot_max_size"].initial or "0",
                "delete_after": defaults_form.fields["delete_after"].initial or "0",
                "crawl_max_concurrent_snapshots": defaults_form.fields["crawl_max_concurrent_snapshots"].initial,
                "persona": defaults_form.fields["persona"].initial or "Default",
                "permissions": defaults_form.fields["permissions"].initial or "public",
                "config": "{}",
            },
        )
        if defaults_form.fields["start_paused"].initial:
            form_data["start_paused"] = "on"

        form = self.form_class(data=form_data)
        if not form.is_valid():
            return self.form_invalid(form)

        crawl = self._create_crawl_from_form(form)
        snapshot = Snapshot.from_json({"url": add_url, "tags": form.cleaned_data.get("tag", "")}, overrides={"crawl": crawl})
        assert snapshot is not None
        return redirect(f"/{snapshot.url_path}")
