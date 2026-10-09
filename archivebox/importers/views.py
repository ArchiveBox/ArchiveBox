from functools import wraps
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from archivebox.config.common import get_request_config
from archivebox.core.admin_site import archivebox_admin
from archivebox.crawls.schedule_util import next_run_for_schedule
from archivebox.plugins.discovery import get_plugin_catalog

from .catalog import get_importer, get_importers
from .forms import ImporterSourceForm
from .models import ImporterRun, ImporterSource
from .service import ACTIVE_STATUSES, enqueue, pause


def importer_admin(view):
    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied("Importer access requires a superuser account.")
        return view(request, *args, **kwargs)

    return wrapped


def page(request, template, context):
    return render(request, template, {**archivebox_admin.each_context(request), **context})


@importer_admin
@require_GET
def index(request):
    definitions = get_importers()
    providers = {}
    for definition in definitions.values():
        group = providers.setdefault(definition.provider, {"name": definition.provider, "definition": definition, "feeds": []})
        group["feeds"].append(definition)
    sources = list(
        ImporterSource.objects.select_related("persona").prefetch_related(
            Prefetch("runs", queryset=ImporterRun.objects.order_by("-created_at", "-id")[:1], to_attr="latest_runs"),
        ),
    )
    for source in sources:
        source.definition = definitions.get((source.plugin, source.feed))
        source.latest_run = next(iter(source.latest_runs), None)
    return page(request, "importers/index.html", {"sources": sources, "providers": providers.values(), "title": "Importers"})


@importer_admin
@require_http_methods(["GET", "POST"])
def configure(request, plugin=None, feed=None, source_id=None):
    source = get_object_or_404(ImporterSource, pk=source_id) if source_id else ImporterSource(created_by=request.user)
    try:
        definition = get_importer(source.plugin if source_id else plugin, source.feed if source_id else feed)
    except ValueError as error:
        raise Http404(str(error)) from error
    if source_id and source.runs.filter(status__in=ACTIVE_STATUSES).exists():
        messages.error(request, "Wait for the active run to finish, or pause it before editing.")
        return redirect(source)
    original_settings, original_persona = source.settings, source.persona_id
    original_checkpoint = source.checkpoint
    form = ImporterSourceForm(request.POST if request.method == "POST" else None, instance=source, definition=definition)
    if request.method == "POST" and form.is_valid():
        source = form.save(commit=False)
        if source.checkpoint and (source.settings != original_settings or source.persona_id != original_persona):
            form.add_error(None, "Reset progress on the importer before changing its source settings or persona.")
        else:
            source.next_run_at = next_run_for_schedule(source.schedule, timezone.now()) if source.schedule and source.enabled else None
            if source_id:
                saved = (
                    ImporterSource.objects.filter(pk=source.pk, checkpoint=original_checkpoint)
                    .exclude(runs__status__in=ACTIVE_STATUSES)
                    .update(
                        **{key: getattr(source, key) for key in (*form._meta.fields, "settings", "next_run_at")},
                    )
                )
                if not saved:
                    messages.error(request, "The importer started or its progress changed. Pause it and reload before editing.")
                    return redirect(source)
            else:
                source.save()
            messages.success(request, "Importer saved. Check access or preview the first items before importing.")
            return redirect(source)
    return page(
        request,
        "importers/configure.html",
        {"form": form, "source": source, "definition": definition, "title": "Configure importer"},
    )


@importer_admin
@require_GET
def detail(request, source_id):
    source = get_object_or_404(ImporterSource.objects.select_related("persona"), pk=source_id)
    definition = get_importers().get((source.plugin, source.feed))
    runs = list(source.runs.select_related("crawl")[:20])
    active = source.runs.filter(status__in=ACTIVE_STATUSES).first()
    return page(
        request,
        "importers/detail.html",
        {
            "title": source.name,
            "source": source,
            "definition": definition,
            "runs": runs,
            "active": active,
        },
    )


@importer_admin
@require_POST
def action(request, source_id, action):
    source = get_object_or_404(ImporterSource, pk=source_id)
    try:
        if action in ImporterRun.Action.values:
            run = enqueue(source, action)
            messages.success(request, f"{run.get_action_display()} queued. The ArchiveBox worker will process it.")
        elif action == "pause":
            pause(source)
            messages.success(request, "Schedule paused. Any active importer is being cancelled.")
        elif action == "resume":
            source.enabled = True
            source.next_run_at = next_run_for_schedule(source.schedule, timezone.now()) if source.schedule else None
            source.save(update_fields=["enabled", "next_run_at"])
            messages.success(request, "Importer resumed.")
        elif action == "reset":
            if not ImporterSource.objects.filter(pk=source.pk).exclude(runs__status__in=ACTIVE_STATUSES).update(checkpoint={}, account={}):
                raise ValueError("Pause the importer and wait for its active run before resetting progress.")
            messages.success(request, "Progress reset. Existing captures and run history are preserved.")
        else:
            raise Http404
    except ValueError as error:
        messages.error(request, str(error))
    return redirect(source)


@importer_admin
@require_GET
def run_detail(request, run_id):
    run = get_object_or_404(ImporterRun.objects.select_related("source", "crawl"), pk=run_id)
    return page(request, "importers/run.html", {"title": run.get_action_display(), "run": run, "active": run.status in ACTIVE_STATUSES})


@importer_admin
@require_GET
def run_json(request, run_id):
    run = get_object_or_404(ImporterRun, pk=run_id)
    # Deliberately exclude request settings and opaque checkpoints from export.
    return JsonResponse({"id": str(run.pk), "status": run.status, "action": run.action, "items": run.items, "message": run.message})


@importer_admin
@require_GET
def guide_image(request, plugin, feed, step):
    try:
        definition = get_importer(plugin, feed)
        return plugin_image(plugin, definition.setup[step]["image"])
    except (ValueError, KeyError, IndexError, OSError) as error:
        raise Http404 from error


def plugin_image(plugin, filename):
    root = get_plugin_catalog()[plugin].path.resolve()
    image = (root / Path(filename)).resolve()
    if not image.is_relative_to(root) or image.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        raise Http404
    response = FileResponse(image.open("rb"))
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@importer_admin
@require_GET
def brand_icon(request, plugin, feed):
    try:
        return plugin_image(plugin, get_importer(plugin, feed).icon)
    except (ValueError, KeyError, OSError) as error:
        raise Http404 from error


@importer_admin
@require_POST
def create_custom(request):
    config = get_request_config(request).model_dump(mode="json")
    if not config.get("OPENCODE_ENABLED"):
        messages.error(request, "Enable the OpenCode plugin in server settings to create an importer with AI.")
        return redirect("importers:index")
    from abx_plugins.plugins.opencode.archivebox.views import _runtime_settings

    runtime, settings = _runtime_settings(request, config)
    prompt = Path(__file__).with_name("create_prompt.md").read_text()
    try:
        session = runtime.start_session(settings, title="Create a custom importer", prompt=prompt)
    except (RuntimeError, OSError, ValueError):
        messages.error(request, "The AI session could not start. Check the Agent provider settings, then try again.")
        return redirect("importers:index")
    return redirect(f"/admin/agent/?session={session}")
