__package__ = "archivebox.crawls"

from copy import copy
import json
from urllib.parse import urlencode, urlparse

from django import forms
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpRequest, HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.utils.html import escape, format_html, format_html_join
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.contrib import admin, messages
from django.db.models import Case, CharField, Count, Q, Value, When


from django_object_actions import action

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.core.permissions import (
    PERMISSIONS_CHOICES,
    PERMISSIONS_META,
    PERMISSIONS_PRIVATE,
    PERMISSIONS_PUBLIC,
    PERMISSIONS_UNLISTED,
    PERMISSIONS_VALUES,
    normalize_permissions,
)
from archivebox.core.widgets import TagEditorWidget, URLFiltersWidget
from archivebox.crawls.models import Crawl, CrawlSchedule
from archivebox.misc.paginators import AcceleratedPaginator
from archivebox.progressmonitor.views import progress_endpoint
from archivebox.workers.models import RETRY_AT_MAX


class MaxDepthListFilter(admin.SimpleListFilter):
    title = "max depth"
    parameter_name = "max_depth"

    def lookups(self, request, model_admin):
        return [(str(depth), str(depth)) for depth in range(5)]

    def queryset(self, request, queryset):
        value = self.value()
        if value is not None and value.isdigit():
            return queryset.filter(max_depth=int(value))
        return queryset


def render_snapshots_list(snapshots_qs, request=None, crawl=None, page_size=50, prefix="snapshots"):
    """Render a nice inline list view of snapshots with status, title, URL, and progress."""

    query_param = f"{prefix}_q"
    status_param = f"{prefix}_status"
    page_param = f"{prefix}_page"
    query = (request.GET.get(query_param, "") if request is not None else "").strip()
    status_filter = (request.GET.get(status_param, "") if request is not None else "").strip()
    valid_statuses = {choice[0] for choice in Snapshot.StatusChoices.choices}

    filtered_qs = snapshots_qs
    if query:
        from archivebox.misc.util import filter_queryset_by_uuid_substring

        id_match_pks = list(filter_queryset_by_uuid_substring(Snapshot.objects.all(), query).values_list("pk", flat=True)[:100])
        filtered_qs = filtered_qs.filter(Q(pk__in=id_match_pks) | Q(url__icontains=query) | Q(title__icontains=query))
    if status_filter in valid_statuses:
        filtered_qs = filtered_qs.filter(status=status_filter)

    # Keep ArchiveResult counters as scalar subqueries so the paginated
    # Snapshot queryset does not become a join+GROUP BY over every result row.
    snapshots_qs = filtered_qs.order_by("-created_at").annotate(
        total_results=ArchiveResult.snapshot_count_expr(),
        succeeded_results=ArchiveResult.snapshot_count_expr(status=ArchiveResult.StatusChoices.SUCCEEDED),
        failed_results=ArchiveResult.snapshot_count_expr(status=ArchiveResult.StatusChoices.FAILED),
        started_results=ArchiveResult.snapshot_count_expr(status=ArchiveResult.StatusChoices.STARTED),
        skipped_results=ArchiveResult.snapshot_count_expr(status=ArchiveResult.StatusChoices.SKIPPED),
        snapshot_permissions=Case(
            When(permissions=PERMISSIONS_PUBLIC, then=Value(PERMISSIONS_PUBLIC)),
            When(permissions=PERMISSIONS_UNLISTED, then=Value(PERMISSIONS_UNLISTED)),
            When(permissions=PERMISSIONS_PRIVATE, then=Value(PERMISSIONS_PRIVATE)),
            When(crawl__permissions=PERMISSIONS_PUBLIC, then=Value(PERMISSIONS_PUBLIC)),
            When(crawl__permissions=PERMISSIONS_UNLISTED, then=Value(PERMISSIONS_UNLISTED)),
            When(crawl__permissions=PERMISSIONS_PRIVATE, then=Value(PERMISSIONS_PRIVATE)),
            default=Value(PERMISSIONS_PRIVATE),
            output_field=CharField(),
        ),
    )

    page_number = request.GET.get(page_param, 1) if request is not None else 1
    paginator = Paginator(snapshots_qs, page_size)
    page_obj = paginator.get_page(page_number)
    snapshots = page_obj.object_list
    total_count = paginator.count

    def querystring(**updates):
        if request is None:
            return "#"
        params = request.GET.copy()
        for key, value in updates.items():
            if value in (None, ""):
                params.pop(key, None)
            else:
                params[key] = str(value)
        return f"?{params.urlencode()}" if params else "?"

    preserved_inputs = ""
    if request is not None:
        managed_params = {query_param, status_param, page_param}
        preserved_inputs = "".join(
            f'<input type="hidden" name="{escape(key)}" value="{escape(value)}">'
            for key, values in request.GET.lists()
            if key not in managed_params
            for value in values
        )

    status_options = "".join(
        f'<option value="{escape(value)}"{" selected" if status_filter == value else ""}>{escape(label)}</option>'
        for value, label in Snapshot.StatusChoices.choices
    )

    controls = f"""
        <div class="crawl-snapshots-toolbar" style="display: flex; gap: 10px; align-items: center; justify-content: space-between; flex-wrap: wrap; padding: 10px 12px; background: #f8fafc; border-bottom: 1px solid #e2e8f0;">
            <form method="get" style="display: flex; gap: 8px; align-items: center; flex: 1 1 540px; margin: 0;">
                {preserved_inputs}
                <input type="search" name="{query_param}" value="{escape(query)}" placeholder="Filter snapshots by title, URL, or ID"
                       style="min-width: 260px; flex: 1 1 360px; padding: 7px 10px; border: 1px solid #cbd5e1; border-radius: 6px;">
                <select name="{status_param}" style="max-width: 170px; padding: 7px 10px; border: 1px solid #cbd5e1; border-radius: 6px;">
                    <option value="">All statuses</option>
                    {status_options}
                </select>
                <input type="hidden" name="{page_param}" value="1">
                <button type="submit" class="button" style="padding: 7px 12px;">Filter</button>
                {f'<a href="{querystring(**{query_param: None, status_param: None, page_param: None})}" style="font-size: 12px; color: #64748b;">Clear</a>' if query or status_filter else ""}
            </form>
            <div style="font-size: 12px; color: #64748b; white-space: nowrap;">
                {page_obj.start_index() if total_count else 0}-{page_obj.end_index() if total_count else 0} of {total_count}
            </div>
        </div>
    """

    if not snapshots:
        return mark_safe(f"""
            <div data-crawl-snapshots-list style="border: 1px solid #ddd; border-radius: 6px; overflow: hidden; max-width: 100%;">
                {controls}
                <div style="color: #666; font-style: italic; padding: 12px;">No Snapshots found.</div>
            </div>
        """)

    # Status colors matching Django admin and progress monitor
    status_colors = {
        "queued": ("#6c757d", "#f8f9fa"),  # gray
        "started": ("#856404", "#fff3cd"),  # amber
        "paused": ("#1d4ed8", "#dbeafe"),  # blue
        "sealed": ("#155724", "#d4edda"),  # green
        "failed": ("#721c24", "#f8d7da"),  # red
    }

    rows = []
    for snapshot in snapshots:
        status = snapshot.status or "queued"
        color, bg = status_colors.get(status, ("#6c757d", "#f8f9fa"))
        permissions = snapshot.snapshot_permissions
        permission_icon = {
            PERMISSIONS_PUBLIC: "👁",
            PERMISSIONS_UNLISTED: "🔗",
            PERMISSIONS_PRIVATE: "🔒",
        }[permissions]
        permission_fg, permission_bg = {
            PERMISSIONS_PUBLIC: ("#047857", "#d1fae5"),
            PERMISSIONS_UNLISTED: ("#1d4ed8", "#dbeafe"),
            PERMISSIONS_PRIVATE: ("#991b1b", "#fee2e2"),
        }[permissions]

        # Calculate progress
        total = snapshot.total_results
        succeeded = snapshot.succeeded_results
        failed = snapshot.failed_results
        running = snapshot.started_results
        skipped = snapshot.skipped_results
        done = succeeded + failed + skipped
        pending = max(total - done - running, 0)
        progress_pct = int((done / total) * 100) if total > 0 else 0
        progress_text = f"{done}/{total}" if total > 0 else "-"
        progress_title = f"{succeeded} succeeded, {failed} failed, {running} running, {pending} pending, {skipped} skipped"
        progress_color = "#28a745"
        if failed:
            progress_color = "#dc3545"
        elif running:
            progress_color = "#17a2b8"
        elif pending:
            progress_color = "#ffc107"

        # Truncate title and URL
        snapshot_title = snapshot.title or "Untitled"
        title = snapshot_title[:60]
        if len(snapshot_title) > 60:
            title += "..."
        url_display = snapshot.url[:50]
        if len(snapshot.url) > 50:
            url_display += "..."
        delete_button = ""
        exclude_button = ""
        if crawl is not None:
            delete_url = reverse("admin:crawls_crawl_snapshot_delete", args=[crawl.pk, snapshot.pk])
            exclude_url = reverse("admin:crawls_crawl_snapshot_exclude_domain", args=[crawl.pk, snapshot.pk])
            delete_button = f'''
                <button type="button"
                        class="crawl-snapshots-action"
                        data-post-url="{escape(delete_url)}"
                        data-confirm="Delete this snapshot from the crawl?"
                        title="Delete this snapshot from the crawl and remove its URL from the crawl queue."
                        aria-label="Delete snapshot"
                        style="border: 1px solid #ddd; background: #fff; color: #666; border-radius: 4px; width: 28px; height: 28px; cursor: pointer;">🗑</button>
            '''
            exclude_button = f'''
                <button type="button"
                        class="crawl-snapshots-action"
                        data-post-url="{escape(exclude_url)}"
                        data-confirm="Exclude this domain from the crawl? This removes matching queued URLs, deletes pending matching snapshots, and blocks future matches."
                        title="Exclude this domain from this crawl. This removes matching URLs from the crawl queue, deletes pending matching snapshots, and blocks future matches."
                        aria-label="Exclude domain from crawl"
                        style="border: 1px solid #ddd; background: #fff; color: #666; border-radius: 4px; width: 28px; height: 28px; cursor: pointer;">⊘</button>
            '''

        # Format date
        date_str = snapshot.created_at.strftime("%Y-%m-%d %H:%M") if snapshot.created_at else "-"

        rows.append(f'''
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 6px 8px; white-space: nowrap;">
                    <span style="display: inline-block; padding: 2px 8px; border-radius: 10px;
                                 font-size: 11px; font-weight: 500; text-transform: uppercase;
                                 color: {color}; background: {bg};">{status}</span>
                </td>
                <td style="padding: 6px 8px; white-space: nowrap; text-align: center;">
                    <span title="{permissions}" style="display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:999px; font-size:12px; color:{permission_fg}; background:{permission_bg};">{permission_icon}</span>
                </td>
                <td style="padding: 6px 8px; white-space: nowrap;">
                    <a href="/{snapshot.archive_path}/" style="text-decoration: none;">
                        <img src="/{snapshot.archive_path}/favicon.ico"
                             style="width: 16px; height: 16px; vertical-align: middle; margin-right: 4px;"
                             onerror="this.style.display='none'"/>
                    </a>
                </td>
                <td style="padding: 6px 8px; max-width: 300px;">
                    <a href="{snapshot.admin_change_url}" style="color: #417690; text-decoration: none; font-weight: 500;"
                       title="{escape(snapshot_title)}">{escape(title)}</a>
                </td>
                <td style="padding: 6px 8px; max-width: 250px;">
                    <a href="{escape(snapshot.url)}" target="_blank"
                       style="color: #666; text-decoration: none; font-family: monospace; font-size: 11px;"
                       title="{escape(snapshot.url)}">{escape(url_display)}</a>
                </td>
                <td style="padding: 6px 8px; white-space: nowrap; text-align: center;">
                    <div style="display: inline-flex; align-items: center; gap: 6px;" title="{escape(progress_title)}">
                        <div style="width: 60px; height: 6px; background: #eee; border-radius: 3px; overflow: hidden;">
                            <div style="width: {progress_pct}%; height: 100%;
                                        background: {progress_color};
                                        transition: width 0.3s;"></div>
                        </div>
                        <a href="/admin/core/archiveresult/?snapshot__id__exact={snapshot.id}"
                           style="font-size: 11px; color: #417690; min-width: 35px; text-decoration: none;"
                           title="View archive results">{progress_text}</a>
                    </div>
                </td>
                <td style="padding: 6px 8px; white-space: nowrap; color: #888; font-size: 11px;">
                    {date_str}
                </td>
                {f'<td style="padding: 6px 8px; white-space: nowrap; text-align: right;"><div style="display: inline-flex; gap: 6px;">{exclude_button}{delete_button}</div></td>' if crawl is not None else ""}
            </tr>
        ''')

    pagination = ""
    if paginator.num_pages > 1:
        pagination = f"""
            <div style="display: flex; gap: 10px; align-items: center; justify-content: center; padding: 10px 12px; background: #f8fafc; border-top: 1px solid #e2e8f0; font-size: 12px;">
                {"<a class='button' style='padding: 5px 10px;' href='" + querystring(**{page_param: page_obj.previous_page_number()}) + "'>Previous</a>" if page_obj.has_previous() else "<span style='color:#94a3b8;'>Previous</span>"}
                <span style="color: #64748b;">Page {page_obj.number} of {paginator.num_pages}</span>
                {"<a class='button' style='padding: 5px 10px;' href='" + querystring(**{page_param: page_obj.next_page_number()}) + "'>Next</a>" if page_obj.has_next() else "<span style='color:#94a3b8;'>Next</span>"}
            </div>
        """

    return mark_safe(f"""
        <div data-crawl-snapshots-list style="border: 1px solid #ddd; border-radius: 6px; overflow: hidden; max-width: 100%;">
            {controls}
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <thead>
                    <tr style="background: #f5f5f5; border-bottom: 2px solid #ddd;">
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333;">Status</th>
                        <th style="padding: 8px 4px; text-align: center; font-weight: 600; color: #333; width: 22px;">🔒</th>
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333; width: 24px;"></th>
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333;">Title</th>
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333;">URL</th>
                        <th style="padding: 8px; text-align: center; font-weight: 600; color: #333;">Progress</th>
                        <th style="padding: 8px; text-align: left; font-weight: 600; color: #333;">Created</th>
                        {
        '<th style="padding: 8px; text-align: right; font-weight: 600; color: #333;">Actions</th>' if crawl is not None else ""
    }
                    </tr>
                </thead>
                <tbody>
                    {"".join(rows)}
                </tbody>
            </table>
            {pagination}
        </div>
        {
        '''
        <script>
        (function() {
            if (window.__archiveboxCrawlSnapshotActionsBound) {
                return;
            }
            window.__archiveboxCrawlSnapshotActionsBound = true;

            function getCookie(name) {
                var cookieValue = null;
                if (!document.cookie) {
                    return cookieValue;
                }
                var cookies = document.cookie.split(';');
                for (var i = 0; i < cookies.length; i++) {
                    var cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
                return cookieValue;
            }

            document.addEventListener('click', function(event) {
                var button = event.target.closest('.crawl-snapshots-action');
                if (!button) {
                    return;
                }
                event.preventDefault();

                var confirmMessage = button.getAttribute('data-confirm');
                if (confirmMessage && !window.confirm(confirmMessage)) {
                    return;
                }

                button.disabled = true;

                fetch(button.getAttribute('data-post-url'), {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'X-CSRFToken': getCookie('csrftoken') || '',
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                }).then(function(response) {
                    return response.json().then(function(data) {
                        if (!response.ok) {
                            throw new Error(data.error || 'Request failed');
                        }
                        return data;
                    });
                }).then(function() {
                    window.location.reload();
                }).catch(function(error) {
                    button.disabled = false;
                    window.alert(error.message || 'Request failed');
                });
            });
        })();
        </script>
        '''
        if crawl is not None
        else ""
    }
    """)


class URLFiltersField(forms.Field):
    widget = URLFiltersWidget(source_selector="#id_urls")

    def to_python(self, value):
        if isinstance(value, dict):
            return value
        return {"allowlist": "", "denylist": "", "same_domain_only": False, "subpaths_only": False, "only_new": False}


class CrawlAdminForm(forms.ModelForm):
    """Custom form for Crawl admin to render urls field as textarea."""

    tags_editor = forms.CharField(
        label="Tags",
        required=False,
        widget=TagEditorWidget(),
        help_text="Type tag names and press Enter or Space to add. Click × to remove.",
    )
    url_filters = URLFiltersField(
        label="URL Filters",
        required=False,
        help_text="Set URL_ALLOWLIST / URL_DENYLIST for this crawl.",
    )

    class Meta:
        model = Crawl
        fields = "__all__"
        widgets = {
            "urls": forms.Textarea(
                attrs={
                    "rows": 8,
                    "style": "width: 100%; font-family: monospace; font-size: 13px;",
                    "placeholder": "https://example.com\nhttps://example2.com\n# Comments start with #",
                },
            ),
            "notes": forms.Textarea(
                attrs={
                    "rows": 1,
                    "style": "width: 100%; min-height: 0; resize: vertical;",
                },
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = dict(self.instance.config or {}) if self.instance and self.instance.pk else {}
        if self.instance and self.instance.pk:
            self.initial["tags_editor"] = self.instance.tags_str
        effective_only_new = self.effective_only_new(self.instance if self.instance and self.instance.pk else None)
        derived_filter_toggles = self.derive_filter_toggles(
            self.instance.urls if self.instance and self.instance.pk else "",
            config.get("URL_ALLOWLIST", ""),
        )
        self.initial["url_filters"] = {
            "allowlist": config.get("URL_ALLOWLIST", ""),
            "denylist": config.get("URL_DENYLIST", ""),
            "same_domain_only": derived_filter_toggles["same_domain_only"],
            "subpaths_only": derived_filter_toggles["subpaths_only"],
            "only_new": effective_only_new,
        }

    @staticmethod
    def extract_url_line(line):
        line = str(line or "").strip()
        if not line or line.startswith("#"):
            return ""
        if line.startswith("{"):
            try:
                return str(json.loads(line).get("url", "")).strip()
            except (TypeError, ValueError, json.JSONDecodeError):
                return ""
        return line

    @staticmethod
    def regex_escape(text):
        escaped = ""
        for char in str(text or ""):
            escaped += f"\\{char}" if char in r".*+?^${}()|[]\\" else char
        return escaped

    @classmethod
    def generated_host_allowlist(cls, urls):
        seen = set()
        domains = []
        for raw_line in str(urls or "").splitlines():
            url = cls.extract_url_line(raw_line)
            if not url:
                continue
            parsed = urlparse(url)
            domain = (parsed.hostname or "").lower()
            if not domain or domain in seen:
                continue
            seen.add(domain)
            domains.append(domain)
        if not domains:
            return ""
        return "^https?://(" + "|".join(cls.regex_escape(domain) for domain in domains) + ")([:/]|$)"

    @staticmethod
    def subpath_prefix(pathname):
        path = str(pathname or "/")
        while "//" in path:
            path = path.replace("//", "/")
        if not path or path == "/":
            return "/"
        if path.endswith("/"):
            return path
        last_slash = path.rfind("/")
        last_part = path[last_slash + 1 :]
        if "." in last_part:
            return path[: last_slash + 1] or "/"
        return path

    @staticmethod
    def parsed_host_and_port(parsed):
        host = (parsed.hostname or "").lower()
        if not host:
            return ""
        try:
            port = parsed.port
        except ValueError:
            port = None
        return f"{host}:{port}" if port is not None else host

    @classmethod
    def generated_subpath_allowlist(cls, urls):
        seen = set()
        paths = []
        for raw_line in str(urls or "").splitlines():
            url = cls.extract_url_line(raw_line)
            if not url:
                continue
            parsed = urlparse(url)
            domain = (parsed.hostname or "").lower()
            if domain:
                seen.add(domain)
            host = cls.parsed_host_and_port(parsed)
            path = cls.subpath_prefix(parsed.path)
            path_key = f"{host}{path}"
            if not host or path_key in seen:
                continue
            seen.add(path_key)
            paths.append((host, path))
        if not paths:
            return ""
        patterns = []
        for host, path in paths:
            if path == "/":
                patterns.append(f"^https?://{cls.regex_escape(host)}([/?#]|$)")
            elif path.endswith("/"):
                patterns.append(f"^https?://{cls.regex_escape(host)}{cls.regex_escape(path)}")
            else:
                patterns.append(f"^https?://{cls.regex_escape(host)}{cls.regex_escape(path)}([/?#]|$)")
        return "\n".join(patterns)

    @classmethod
    def derive_filter_toggles(cls, urls, allowlist):
        normalized_allowlist = "\n".join(Crawl.split_filter_patterns(allowlist))
        if not normalized_allowlist:
            return {"same_domain_only": False, "subpaths_only": False}
        if normalized_allowlist == cls.generated_subpath_allowlist(urls):
            return {"same_domain_only": True, "subpaths_only": True}
        if normalized_allowlist == cls.generated_host_allowlist(urls):
            return {"same_domain_only": True, "subpaths_only": False}
        return {"same_domain_only": False, "subpaths_only": False}

    @staticmethod
    def effective_only_new(crawl=None):
        from archivebox.config.common import get_config

        if crawl is not None:
            return bool(get_config(crawl=crawl, resolve_plugins=False).ONLY_NEW)
        return bool(get_config(resolve_plugins=False).ONLY_NEW)

    @staticmethod
    def inherited_only_new(crawl):
        crawl_without_only_new = copy(crawl)
        config = dict(crawl.config or {})
        config.pop("ONLY_NEW", None)
        crawl_without_only_new.config = config
        return CrawlAdminForm.effective_only_new(crawl_without_only_new)

    def clean_tags_editor(self):
        tags_str = self.cleaned_data.get("tags_editor", "")
        tag_names = []
        seen = set()
        for raw_name in tags_str.split(","):
            name = raw_name.strip()
            if not name:
                continue
            lowered = name.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            tag_names.append(name)
        return ",".join(tag_names)

    def clean_url_filters(self):
        value = self.cleaned_data.get("url_filters") or {}
        return {
            "allowlist": "\n".join(Crawl.split_filter_patterns(value.get("allowlist", ""))),
            "denylist": "\n".join(Crawl.split_filter_patterns(value.get("denylist", ""))),
            "same_domain_only": bool(value.get("same_domain_only")),
            "subpaths_only": bool(value.get("subpaths_only")),
            "only_new": bool(value.get("only_new")),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.tags_str = self.cleaned_data.get("tags_editor", "")
        if f"{self.add_prefix('url_filters')}_allowlist" in self.data or f"{self.add_prefix('url_filters')}_denylist" in self.data:
            url_filters = self.cleaned_data.get("url_filters") or {}
            instance.set_url_filters(
                url_filters.get("allowlist", ""),
                url_filters.get("denylist", ""),
            )
            config = dict(instance.config or {})
            only_new = bool(url_filters.get("only_new"))
            inherited_only_new = self.inherited_only_new(instance)
            if only_new != inherited_only_new:
                config["ONLY_NEW"] = only_new
            else:
                config.pop("ONLY_NEW", None)
            instance.config = config
        if commit:
            instance.save()
            instance.apply_crawl_config_filters()
            self._save_m2m()
        return instance


class CrawlAdmin(ConfigEditorMixin, BaseModelAdmin):
    form = CrawlAdminForm
    change_form_template = "admin/crawls/crawl/change_form.html"
    list_select_related = ()
    paginator = AcceleratedPaginator
    show_full_result_count = False
    list_display = (
        "short_id",
        "permissions_badge",
        "created_at",
        "owner",
        "depth",
        "status_with_stop_reason",
        "pause_resume_control",
        "label",
        "notes",
        "urls_preview",
        "schedule_str",
        "retry_at",
        "num_archived_snapshots",
        "num_total_snapshots",
    )
    sort_fields = (
        "id",
        "created_at",
        "created_by",
        "max_depth",
        "label",
        "notes",
        "schedule_str",
        "status",
        "retry_at",
    )
    search_fields = (
        "id",
        "created_by__username",
        "max_depth",
        "label",
        "notes",
        "schedule_id",
        "status",
        "urls",
    )

    readonly_fields = ("created_at", "modified_at", "stop_reason_display")

    fieldsets = (
        (
            "URLs",
            {
                "fields": ("urls", "url_filters"),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Overview",
            {
                "fields": (
                    ("label", "status", "retry_at", "schedule", "created_by", "created_at", "modified_at"),
                    ("max_depth",),
                    ("stop_reason_display",),
                    ("notes", "tags_editor"),
                ),
                "classes": ("card", "wide", "crawl-admin-overview"),
            },
        ),
        (
            "Config",
            {
                "fields": ("config",),
                "classes": ("card", "wide", "crawl-admin-config"),
            },
        ),
    )
    add_fieldsets = (
        (
            "URLs",
            {
                "fields": ("urls", "url_filters"),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Overview",
            {
                "fields": (
                    ("label", "status", "retry_at", "schedule", "created_by"),
                    ("max_depth",),
                    ("notes", "tags_editor"),
                ),
                "classes": ("card", "wide", "crawl-admin-overview"),
            },
        ),
        (
            "Config",
            {
                "fields": ("config",),
                "classes": ("card", "wide", "crawl-admin-config"),
            },
        ),
    )

    list_filter = (MaxDepthListFilter, "schedule", "created_by", "status", "retry_at")
    ordering = ["-created_at", "-retry_at"]
    list_per_page = 50
    actions = [
        "pause_selected_crawls",
        "resume_selected_crawls",
        "seal_selected_crawls",
        "delete_selected_batched",
        "set_crawl_permissions",
    ]
    change_actions = ["recrawl"]

    def __init__(self, model, admin_site):
        super().__init__(model, admin_site)
        self.crawl_admin_base_config = None
        self.stop_reason_cache = {}

    class Media:
        css = {"all": ("admin/crawls/crawl_change.css",)}
        js = ("admin/crawls/crawl_admin.js",)

    def changelist_view(self, request, extra_context=None):
        self.request = request
        self.crawl_admin_base_config = request.archivebox_config
        self.stop_reason_cache = {}
        response = super().changelist_view(request, extra_context)
        if not isinstance(response, TemplateResponse):
            return response
        cl = response.context_data.get("cl")
        if cl is not None and not self.should_annotate_snapshot_counts(request):
            self.hydrate_visible_snapshot_counts(cl.result_list)
        return response

    def should_annotate_snapshot_counts(self, request):
        ordering = request.GET.get("o", "")
        if not ordering:
            return False
        list_display = list(self.get_list_display(request))
        count_positions = {
            str(list_display.index("num_archived_snapshots") + 1),
            str(list_display.index("num_total_snapshots") + 1),
        }
        return any(part.lstrip("-") in count_positions for part in ordering.split("."))

    def hydrate_visible_snapshot_counts(self, crawls):
        crawl_list = list(crawls)
        crawl_ids = [crawl.pk for crawl in crawl_list]
        if not crawl_ids:
            return
        counts = Snapshot.crawl_total_and_status_counts(crawl_ids, status=Snapshot.StatusChoices.SEALED)
        for crawl in crawl_list:
            row = counts.get(str(crawl.pk), {})
            crawl.num_snapshots_cached = row.get("total", 0)
            crawl.num_archived_snapshots_cached = row.get("status", 0)

    def get_queryset(self, request):
        """Keep joins page-local while computing per-row snapshot counts in the page query."""
        queryset = (
            super()
            .get_queryset(request)
            .prefetch_related(
                "created_by",
                "persona",
                "schedule__template",
            )
        )
        if self.should_annotate_snapshot_counts(request):
            queryset = queryset.annotate(
                num_snapshots_cached=Snapshot.crawl_count_expr(),
                num_archived_snapshots_cached=Snapshot.crawl_count_expr(status=Snapshot.StatusChoices.SEALED),
            )
        return queryset

    def change_view(self, request, object_id, form_url="", extra_context=None):
        self.request = request
        self.crawl_admin_base_config = request.archivebox_config
        self.stop_reason_cache = {}
        crawl = self.get_object(request, object_id)
        if crawl:
            self.hydrate_visible_snapshot_counts([crawl])
        extra_context = {
            **(extra_context or {}),
            "crawl_stop_reason": self.stop_reason_for_crawl(crawl) if crawl else "",
            "crawl_snapshots_changelist": self.snapshots_changelist(crawl) if crawl else "",
        }
        if crawl and crawl.status in {
            Crawl.StatusChoices.QUEUED,
            Crawl.StatusChoices.STARTED,
            Crawl.StatusChoices.PAUSED,
        }:
            extra_context["progress_auto_expand"] = True
            extra_context["progress_endpoint"] = progress_endpoint("crawl", crawl.id)
        return super().change_view(request, object_id, form_url, extra_context)

    def add_view(self, request, form_url="", extra_context=None):
        self.request = request
        return super().add_view(request, form_url, extra_context)

    def get_fieldsets(self, request, obj=None):
        return self.fieldsets if obj else self.add_fieldsets

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/snapshot/<path:snapshot_id>/delete/",
                self.admin_site.admin_view(self.delete_snapshot_view),
                name="crawls_crawl_snapshot_delete",
            ),
            path(
                "<path:object_id>/snapshot/<path:snapshot_id>/exclude-domain/",
                self.admin_site.admin_view(self.exclude_domain_view),
                name="crawls_crawl_snapshot_exclude_domain",
            ),
            path(
                "<path:object_id>/set-permissions/",
                self.admin_site.admin_view(self.set_permissions_view),
                name="crawls_crawl_set_permissions",
            ),
        ]
        return custom_urls + urls

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(description="Delete")
    def delete_selected_batched(self, request, queryset):
        """Delete crawls in a single transaction to avoid SQLite concurrency issues."""
        from django.db import transaction

        total = queryset.count()

        # Get list of IDs to delete first (outside transaction)
        ids_to_delete = list(queryset.values_list("pk", flat=True))

        # Delete everything in a single atomic transaction
        with transaction.atomic():
            deleted_count, _ = Crawl.objects.filter(pk__in=ids_to_delete).delete()

        messages.success(request, f"Successfully deleted {total} crawls ({deleted_count} total objects including related records).")

    @admin.action(description="Pause")
    def pause_selected_crawls(self, request, queryset):
        # Admin changelist actions must stay set-based. Calling crawl.pause()
        # here fans out into per-crawl Snapshot/ArchiveResult writes and can
        # hold SQLite behind the request for minutes on large archives. The
        # Crawl row is the scheduler signal; the runner observes PAUSED and
        # owns child-row lifecycle work.
        paused = queryset.exclude(status__in=Crawl.INACTIVE_STATES).update(
            status=Crawl.StatusChoices.PAUSED,
            retry_at=RETRY_AT_MAX,
            modified_at=timezone.now(),
        )
        if paused:
            messages.success(request, f"Paused {paused} crawl(s). The runner will stop scheduling new work on the next sweep.")
        else:
            messages.warning(request, "No active crawls were selected to pause.")

    @admin.action(description="Resume")
    def resume_selected_crawls(self, request, queryset):
        # Keep resume symmetrical with pause: one tight scheduler UPDATE, no
        # save() hooks and no child fanout in the request path. Paused child
        # rows become runnable through their own resume/maintenance paths.
        now = timezone.now()
        resumed = queryset.filter(status__in=Crawl.INACTIVE_STATES).update(
            status=Crawl.StatusChoices.QUEUED,
            retry_at=now,
            modified_at=now,
        )
        # A manual resume clears the frozen START_PAUSED flag so it sticks. Only
        # the (small) subset of selected rows that were start-paused needs a
        # per-row config rewrite; everything else stays a single set-based UPDATE.
        batch = []
        for crawl in queryset.filter(config__START_PAUSED=True).only("id", "config").iterator(chunk_size=500):
            config = dict(crawl.config or {})
            config.pop("START_PAUSED", None)
            crawl.config = config
            crawl.modified_at = now
            batch.append(crawl)
            if len(batch) >= 500:
                Crawl.objects.bulk_update(batch, ["config", "modified_at"], batch_size=500)
                batch.clear()
        if batch:
            Crawl.objects.bulk_update(batch, ["config", "modified_at"], batch_size=500)
        if resumed:
            messages.success(request, f"Resumed {resumed} crawl(s). The runner will pick them up on the next sweep.")
        else:
            messages.warning(request, "No paused or sealed crawls were selected to resume.")

    @admin.action(description="Seal")
    def seal_selected_crawls(self, request, queryset):
        now = timezone.now()
        crawl_ids = list(queryset.exclude(status=Crawl.StatusChoices.SEALED).values_list("pk", flat=True))
        if not crawl_ids:
            messages.warning(request, "No unsealed crawls were selected to seal.")
            return

        Snapshot.objects.filter(
            crawl_id__in=crawl_ids,
            status__in=Snapshot.OPEN_STATES,
        ).filter(
            Q(retry_at__isnull=True) | Q(retry_at__gt=now),
        ).update(
            retry_at=now,
            modified_at=now,
        )
        sealed = (
            Crawl.objects.filter(pk__in=crawl_ids)
            .exclude(status=Crawl.StatusChoices.SEALED)
            .update(
                status=Crawl.StatusChoices.SEALED,
                retry_at=now,
                modified_at=now,
            )
        )
        messages.success(request, f"Sealed {sealed} crawl(s). The runner will finish cleanup on the next sweep.")

    @admin.action(description="Permissions ▾")
    def set_crawl_permissions(self, request, queryset):
        permissions = (request.POST.get("permissions") or "").strip().lower()
        if permissions not in PERMISSIONS_VALUES:
            messages.error(request, "Choose a valid permissions value.")
            return
        updated = self.update_crawl_permissions(queryset, permissions)
        messages.success(request, f"Set permissions to {permissions} on {updated} crawl(s).")

    def update_crawl_permissions(self, queryset, permissions):
        now = timezone.now()
        updated = 0
        batch = []
        for crawl in queryset.only("id", "config").iterator(chunk_size=500):
            config = dict(crawl.config or {})
            config["PERMISSIONS"] = permissions
            crawl.config = config
            crawl.modified_at = now
            batch.append(crawl)
            if len(batch) >= 500:
                Crawl.objects.bulk_update(batch, ["config", "modified_at"], batch_size=500)
                updated += len(batch)
                batch.clear()
        if batch:
            Crawl.objects.bulk_update(batch, ["config", "modified_at"], batch_size=500)
            updated += len(batch)
        return updated

    @action(label="Recrawl", description="Create a new crawl with the same settings", methods=("POST",))
    def recrawl(self, request, obj):
        """Duplicate this crawl as a new crawl with the same URLs and settings."""

        # Validate URLs (required for crawl to start)
        if not obj.urls:
            messages.error(request, "Cannot recrawl: original crawl has no URLs.")
            return redirect("admin:crawls_crawl_change", obj.id)

        new_crawl = Crawl.create_scheduler_row(
            urls=obj.urls,
            max_depth=obj.max_depth,
            tags_str=obj.tags_str,
            config=obj.config,
            schedule=obj.schedule,
            label=f"{obj.label} (recrawl)" if obj.label else "",
            notes=obj.notes,
            created_by=request.user,
            status=Crawl.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )

        messages.success(request, f"Created new crawl {new_crawl.id} with the same settings. It will start processing shortly.")

        return redirect("admin:crawls_crawl_change", new_crawl.id)

    @admin.display(description="Stop Reason")
    def stop_reason_display(self, obj):
        reason = self.stop_reason_for_crawl(obj) if obj else ""
        if not reason:
            return mark_safe('<span class="crawl-stop-reason crawl-stop-reason--empty">None</span>')
        return format_html('<span class="crawl-stop-reason">{}</span>', reason)

    def stop_reason_for_crawl(self, obj):
        if obj.pk in self.stop_reason_cache:
            return self.stop_reason_cache[obj.pk]

        output_dir = obj.output_dir
        config = self.limit_config_for_crawl(obj, output_dir)
        reason = obj.stop_reason(
            config=config,
            output_dir=output_dir,
            num_snapshots=obj.num_snapshots_cached,
            num_sealed_snapshots=obj.num_archived_snapshots_cached,
        )
        self.stop_reason_cache[obj.pk] = reason
        return reason

    def limit_config_for_crawl(self, obj, output_dir):
        from archivebox.config.common import get_config

        return get_config(crawl=obj).for_crawl_runtime(
            crawl=obj,
            persona=obj.resolve_persona(),
            crawl_output_dir=output_dir,
        )

    @admin.display(description="Status", ordering="status")
    def status_with_stop_reason(self, obj):
        status = "PAUSED" if obj.is_paused else str(obj.status or "").upper()
        reason = self.stop_reason_for_crawl(obj) if obj.is_paused or obj.status == Crawl.StatusChoices.SEALED else ""
        if reason:
            reason_label = reason.removeprefix("crawl_").replace("_", " ")
            return format_html(
                '<span class="crawl-status-group"><span class="crawl-status crawl-status--{}">{}</span><span class="crawl-status-reason crawl-status-reason--{}">{}</span></span>',
                obj.status,
                status,
                reason,
                reason_label,
            )
        return format_html('<span class="crawl-status crawl-status--{}">{}</span>', obj.status, status)

    @admin.display(description="ID", ordering="id")
    def short_id(self, obj):
        short_id = str(obj.pk)[-8:]
        return format_html('<a href="{}">{}</a>', obj.admin_change_url, short_id)

    @admin.display(description="Owner", ordering="created_by")
    def owner(self, obj):
        return obj.created_by

    @admin.display(description="Depth", ordering="max_depth")
    def depth(self, obj):
        return obj.max_depth

    @admin.display(description="👁", ordering="permissions")
    def permissions_badge(self, obj):
        permissions = normalize_permissions(obj.permissions)
        icon, label, fg, bg = PERMISSIONS_META[permissions]
        menu_items = format_html_join(
            "",
            (
                '<button type="button" class="snapshot-permissions-menu-item{}" data-permissions="{}">'
                '<span class="snapshot-permissions-icon" aria-hidden="true" style="color:{}; background:{};">{}</span>'
                "<span>{}</span>"
                "</button>"
            ),
            (
                (
                    " is-active" if choice_value == permissions else "",
                    choice_value,
                    choice_fg,
                    choice_bg,
                    choice_icon,
                    choice_label,
                )
                for choice_value, choice_label in PERMISSIONS_CHOICES
                for choice_icon, _choice_title, choice_fg, choice_bg in [PERMISSIONS_META[choice_value]]
            ),
        )
        return format_html(
            '<span class="snapshot-permissions-quick" data-current-permissions="{}" data-permissions-url="{}">'
            '<button type="button" class="snapshot-permissions-button snapshot-permissions-{}" title="{}" aria-label="Change crawl permissions: {}" aria-expanded="false">'
            '<span class="snapshot-permissions-icon" aria-hidden="true" style="color:{}; background:{};">{}</span>'
            "</button>"
            '<span class="snapshot-permissions-menu" role="menu" hidden>{}</span>'
            "</span>",
            permissions,
            reverse(f"{self.admin_site.name}:crawls_crawl_set_permissions", args=[obj.pk]),
            permissions,
            label,
            label,
            fg,
            bg,
            icon,
            menu_items,
        )

    @admin.display(description="Pause")
    def pause_resume_control(self, obj):
        if obj.is_paused or obj.status == Crawl.StatusChoices.SEALED:
            reason = "paused" if obj.is_paused else (self.stop_reason_for_crawl(obj) or "sealed")
            return format_html(
                '<button type="button" class="button crawl-resume-row" data-crawl-id="{}" title="Resume crawl. Stop reason: {}">Resume</button>',
                obj.pk,
                reason,
            )
        return format_html(
            '<button type="button" class="button crawl-pause-row" data-crawl-id="{}" title="Pause crawl">Pause</button>',
            obj.pk,
        )

    @admin.display(description="Archived", ordering="num_archived_snapshots_cached")
    def num_archived_snapshots(self, obj):
        return obj.num_archived_snapshots_cached

    @admin.display(description="Snapshots", ordering="num_snapshots_cached")
    def num_total_snapshots(self, obj):
        return obj.num_snapshots_cached

    @admin.display(description="Snapshots")
    def snapshots_changelist(self, obj):
        request = self.request
        snapshot_changelist = reverse("admin:core_snapshot_changelist")
        scoped_params = {"crawl_id": str(obj.pk)}
        full_url = f"{snapshot_changelist}?{urlencode(scoped_params)}"

        snapshot_admin = self.admin_site._registry[Snapshot]
        changelist_request = copy(request)
        changelist_request.method = "GET"
        changelist_request.path = snapshot_changelist
        changelist_request.GET = request.GET.copy()
        changelist_request.GET.update(
            {
                **scoped_params,
                "_embedded": "crawl",
                "per_page": "200",
            },
        )
        changelist_request.POST = request.POST.copy()
        changelist_request.POST.clear()

        response = snapshot_admin.changelist_view(
            changelist_request,
            extra_context={"embedded_changelist": True},
        )
        context = {
            **response.context_data,
            "snapshot_changelist_url": full_url,
            "crawl": obj,
        }
        return mark_safe(render_to_string("admin/crawls/crawl/snapshots_changelist.html", context, request=request))

    def delete_snapshot_view(self, request: HttpRequest, object_id: str, snapshot_id: str):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        crawl = get_object_or_404(Crawl, pk=object_id)
        snapshot = get_object_or_404(Snapshot, pk=snapshot_id, crawl=crawl)

        if snapshot.status == Snapshot.StatusChoices.STARTED:
            snapshot.cancel_running_hooks()

        removed_urls = crawl.prune_url(snapshot.url)
        snapshot.delete()
        return JsonResponse(
            {
                "ok": True,
                "snapshot_id": str(snapshot.id),
                "removed_urls": removed_urls,
            },
        )

    def exclude_domain_view(self, request: HttpRequest, object_id: str, snapshot_id: str):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        crawl = get_object_or_404(Crawl, pk=object_id)
        snapshot = get_object_or_404(Snapshot, pk=snapshot_id, crawl=crawl)
        result = crawl.exclude_domain(snapshot.url)
        return JsonResponse(
            {
                "ok": True,
                **result,
            },
        )

    def set_permissions_view(self, request: HttpRequest, object_id: str):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        permissions = (request.POST.get("permissions") or "").strip().lower()
        if permissions not in PERMISSIONS_VALUES:
            return HttpResponseBadRequest("Invalid permissions value")

        crawl = get_object_or_404(Crawl, pk=object_id)
        self.update_crawl_permissions(Crawl.objects.filter(pk=crawl.pk), permissions)
        icon, label, fg, bg = PERMISSIONS_META[permissions]
        return JsonResponse({"permissions": permissions, "icon": icon, "label": label, "fg": fg, "bg": bg})

    @admin.display(description="Schedule", ordering="schedule")
    def schedule_str(self, obj):
        if not obj.schedule:
            return mark_safe("<i>None</i>")
        return format_html('<a href="{}">{}</a>', obj.schedule.admin_change_url, obj.schedule)

    @admin.display(description="URLs", ordering="urls")
    def urls_preview(self, obj):
        first_url = next((line.strip() for line in (obj.urls or "").splitlines() if line.strip() and not line.strip().startswith("#")), "")
        return first_url[:80] + "..." if len(first_url) > 80 else first_url

    @admin.display(description="URLs")
    def urls_editor(self, obj):
        """Editor for crawl URLs."""
        widget_id = f"crawl_urls_{obj.pk}"

        # Escape for safe HTML embedding
        escaped_urls = (obj.urls or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

        # Count lines for auto-expand logic
        line_count = len((obj.urls or "").split("\n"))
        uri_rows = min(max(3, line_count), 10)

        html = f'''
        <div id="{widget_id}_container" style="max-width: 900px;">
            <!-- URLs input -->
            <div style="margin-bottom: 12px;">
                <label style="font-weight: bold; display: block; margin-bottom: 4px;">URLs (one per line):</label>
                <textarea id="{widget_id}_urls"
                          style="width: 100%; font-family: monospace; font-size: 13px;
                                 padding: 8px; border: 1px solid #ccc; border-radius: 4px;
                                 resize: vertical;"
                          rows="{uri_rows}"
                          placeholder="https://example.com&#10;https://example2.com&#10;# Comments start with #"
                          readonly>{escaped_urls}</textarea>
                <p style="color: #666; font-size: 12px; margin: 4px 0 0 0;">
                    {line_count} URL{"s" if line_count != 1 else ""} · Note: URLs displayed here for reference only
                </p>
            </div>
        </div>
        '''
        return mark_safe(html)


class CrawlScheduleAdmin(BaseModelAdmin):
    list_display = ("id", "created_at", "created_by", "label", "notes", "template_str", "crawls", "num_crawls", "num_snapshots")
    sort_fields = ("id", "created_at", "created_by", "label", "notes", "template_str")
    search_fields = ("id", "created_by__username", "label", "notes", "schedule_id", "template_id", "template__urls")

    readonly_fields = ("created_at", "modified_at", "crawls", "snapshots")

    fieldsets = (
        (
            "Schedule Info",
            {
                "fields": ("label", "notes"),
                "classes": ("card",),
            },
        ),
        (
            "Configuration",
            {
                "fields": ("schedule", "template"),
                "classes": ("card",),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_by", "created_at", "modified_at"),
                "classes": ("card",),
            },
        ),
        (
            "Crawls",
            {
                "fields": ("crawls",),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Snapshots",
            {
                "fields": ("snapshots",),
                "classes": ("card", "wide"),
            },
        ),
    )

    list_filter = ("created_by",)
    ordering = ["-created_at"]
    list_per_page = 100
    actions = ["delete_selected"]

    def get_queryset(self, request):
        self.request = request
        return (
            super()
            .get_queryset(request)
            .select_related("created_by", "template")
            .annotate(
                crawl_count=Count("crawl", distinct=True),
                snapshot_count=Count("crawl__snapshot_set", distinct=True),
            )
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        self.request = request
        return super().change_view(request, object_id, form_url, extra_context)

    def add_view(self, request, form_url="", extra_context=None):
        return redirect("/add/#schedule")

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return tuple(fieldset for fieldset in self.fieldsets if fieldset[0] not in {"Crawls", "Snapshots"})
        return self.fieldsets

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id and request.user.is_authenticated:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="Template", ordering="template")
    def template_str(self, obj):
        return format_html('<a href="{}">{}</a>', obj.template.admin_change_url, obj.template)

    @admin.display(description="# Crawls", ordering="crawl_count")
    def num_crawls(self, obj):
        count = obj.__dict__.get("crawl_count")
        if count is None:
            count = obj.crawl_set.count()
        return count

    @admin.display(description="# Snapshots", ordering="snapshot_count")
    def num_snapshots(self, obj):
        count = obj.__dict__.get("snapshot_count")
        if count is None:
            count = Snapshot.objects.filter(crawl__schedule=obj).count()
        return count

    def crawls(self, obj):
        return format_html_join(
            "<br/>",
            ' - <a href="{}">{}</a>',
            ((crawl.admin_change_url, crawl) for crawl in obj.crawl_set.all().order_by("-created_at")[:20]),
        ) or mark_safe("<i>No Crawls yet...</i>")

    def snapshots(self, obj):
        crawl_ids = obj.crawl_set.values_list("pk", flat=True)
        return render_snapshots_list(
            Snapshot.objects.filter(crawl_id__in=crawl_ids),
            request=self.request,
            prefix="schedule_snapshots",
        )


def register_admin(admin_site):
    admin_site.register(Crawl, CrawlAdmin)
    admin_site.register(CrawlSchedule, CrawlScheduleAdmin)
