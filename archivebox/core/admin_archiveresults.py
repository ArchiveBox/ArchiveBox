__package__ = "archivebox.core"

import html
import json
import os
import shlex
from functools import reduce
from operator import and_
from pathlib import Path
from urllib.parse import quote

from django.contrib import admin
from django.contrib.admin.actions import delete_selected
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.exceptions import PermissionDenied, SuspiciousOperation, ValidationError
from django.db.models import Count, Min, Prefetch, Q, Subquery, TextField, Window
from django.db.models.functions import Cast
from django.shortcuts import redirect
from django.urls import resolve, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.text import smart_split

from archivebox.base_models.admin import BaseModelAdmin
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.core.routes_util import build_snapshot_url
from archivebox.core.widgets import InlineTagEditorWidget
from archivebox.machine.env_util import env_to_shell_exports
from archivebox.misc.logging_util import printable_filesize
from archivebox.misc.paginators import AcceleratedPaginator
from archivebox.plugins.discovery import get_plugin_icon
from archivebox.plugins.views import LIVE_PLUGIN_BASE_URL


def _get_replay_source_url(result: ArchiveResult) -> str:
    process = result.process_record
    return str((process.url if process else None) or result.snapshot.url or "")


def build_abx_dl_display_command(result: ArchiveResult) -> str:
    source_url = _get_replay_source_url(result)
    plugin_name = str(result.plugin or "").strip()
    cmd = ["abx-dl"]
    if plugin_name:
        cmd.append(f"--plugins={plugin_name}")
    if source_url:
        cmd.append(source_url)
    return shlex.join(cmd)


def build_abx_dl_replay_command(result: ArchiveResult, config=None) -> str:
    display_command = build_abx_dl_display_command(result)
    process = result.process
    env_items = env_to_shell_exports(process.env if process else {})
    if config is not None:
        result.snapshot._runtime_config = config
    snapshot_dir = shlex.quote(str(result.pwd or result.snapshot_dir))
    if env_items:
        return f"cd {snapshot_dir}; env {env_items} {display_command}"
    return f"cd {snapshot_dir}; {display_command}"


def get_plugin_admin_url(plugin_name: str) -> str:
    from archivebox.plugins.discovery import BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR, iter_plugin_dirs

    plugin_dir = next((path.resolve() for path in iter_plugin_dirs() if path.name == plugin_name), None)
    if plugin_dir:
        builtin_root = BUILTIN_PLUGINS_DIR.resolve()
        if plugin_dir.is_relative_to(builtin_root):
            return f"{LIVE_PLUGIN_BASE_URL}builtin.{quote(plugin_name)}/"

        user_root = USER_PLUGINS_DIR.resolve()
        if plugin_dir.is_relative_to(user_root):
            return f"{LIVE_PLUGIN_BASE_URL}user.{quote(plugin_name)}/"

    return f"{LIVE_PLUGIN_BASE_URL}builtin.{quote(plugin_name)}/"


def get_process_link_label(process) -> str:
    if process.pid:
        return str(process.pid)
    return str(process.id)[-8:]


def render_archiveresults_list(archiveresults_qs, limit=50, config=None, can_delete=False):
    """Render a nice inline list view of archive results with status, plugin, output, and actions."""

    results = list(
        ArchiveResult.objects.filter(pk__in=Subquery(archiveresults_qs.order_by().values("pk")))
        .order_by("plugin")
        .annotate(_inline_total_count=Window(expression=Count("pk")))
        .select_related(
            "snapshot",
            "snapshot__crawl",
            "snapshot__crawl__created_by",
            "process",
            "process__machine",
        )
        .all()[:limit],
    )

    if not results:
        return mark_safe('<div style="color: #64748b; font-style: italic; padding: 16px 0;">No Archive Results yet...</div>')

    # Status colors
    status_colors = {
        "succeeded": ("#166534", "#dcfce7"),  # green
        "failed": ("#991b1b", "#fee2e2"),  # red
        "queued": ("#6b7280", "#f3f4f6"),  # gray
        "started": ("#92400e", "#fef3c7"),  # amber
        "paused": ("#1d4ed8", "#dbeafe"),  # blue
        "backoff": ("#92400e", "#fef3c7"),
        "skipped": ("#475569", "#f1f5f9"),
        "noresults": ("#475569", "#f1f5f9"),
    }

    rows = []
    delete_url = html.escape(reverse("admin:core_archiveresult_changelist"), quote=True)
    for idx, result in enumerate(results):
        status = result.status or "queued"
        color, bg = status_colors.get(status, ("#6b7280", "#f3f4f6"))
        output_files = result.output_files or {}
        if isinstance(output_files, (dict, list, tuple, set)):
            output_file_count = len(output_files)
        elif isinstance(output_files, str):
            try:
                parsed = json.loads(output_files)
                output_file_count = len(parsed) if isinstance(parsed, (dict, list, tuple, set)) else 0
            except (TypeError, ValueError):
                output_file_count = 0
        else:
            output_file_count = 0
        output_size = int(result.output_size or 0)
        output_size_display = html.escape(printable_filesize(output_size))

        # Get plugin icon
        icon = get_plugin_icon(result.plugin)

        # Keep each timestamp component intact while allowing one wrap between them.
        if result.end_ts:
            end_time = (
                f'<span style="white-space: nowrap;">{result.end_ts:%Y-%m-%d}</span>'
                f'<wbr> <span style="white-space: nowrap;">{result.end_ts:%H:%M:%S}</span>'
            )
        else:
            end_time = "-"

        process = result.process_record
        process_display = "-"
        if process:
            process_url = html.escape(reverse("admin:machine_process_change", args=[process.id]), quote=True)
            process_label = html.escape(get_process_link_label(process), quote=True)
            process_display = f'''
                <a href="{process_url}"
                   style="color: #2563eb; text-decoration: none; font-family: ui-monospace, monospace; font-size: 12px;"
                   title="View process">{process_label}</a>
            '''

        machine_display = "-"
        if process and process.machine_id:
            machine_url = html.escape(reverse("admin:machine_machine_change", args=[process.machine_id]), quote=True)
            machine_label = html.escape(str(process.machine.hostname or ""), quote=True)
            machine_display = f'''
                <a href="{machine_url}"
                   style="color: #2563eb; text-decoration: none; font-size: 12px;"
                   title="View machine">{machine_label}</a>
            '''

        # Truncate output for display
        full_output_raw = result.output_str_for_display() or "-"
        output_display_raw = full_output_raw[:60]
        if len(full_output_raw) > 60:
            output_display_raw += "..."
        full_output = html.escape(full_output_raw)
        output_display = html.escape(output_display_raw)

        display_cmd = build_abx_dl_display_command(result)
        replay_cmd = build_abx_dl_replay_command(result, config=config)
        cmd_str_escaped = html.escape(display_cmd)
        cmd_attr = html.escape(replay_cmd, quote=True)

        # Build output link - use embed_path() which checks output_files first
        embed_path = result.embed_path()
        snapshot_id = str(result.snapshot_id)
        if embed_path and result.status == "succeeded":
            output_link = build_snapshot_url(snapshot_id, embed_path, config=config)
        else:
            output_link = build_snapshot_url(snapshot_id, "", config=config)
        output_link_attr = html.escape(output_link, quote=True)

        # Get version - try cmd_version field
        version = html.escape(str(result.cmd_version if result.cmd_version else "-"), quote=True)
        plugin_text = html.escape(str(result.plugin or ""), quote=True)
        status_text = html.escape(str(status), quote=True)
        pwd_text = html.escape(str(result.pwd or "-"), quote=True)

        # Unique ID for this row's expandable output
        row_id = f"output_{idx}_{str(result.id)[:8]}"
        delete_button = ""
        if can_delete:
            delete_button = f'''
                <button type="button" data-archive-result-ids="{result.id}" data-delete-url="{delete_url}"
                        title="Delete this output">×</button>
            '''

        rows.append(f'''
            <tr data-output-size="{output_size}" style="border-bottom: 1px solid #f1f5f9; transition: background 0.15s;" onmouseover="this.style.background='#f8fafc'" onmouseout="this.style.background='transparent'">
                <td style="padding: 10px 12px; white-space: nowrap;">
                    <a href="{reverse("admin:core_archiveresult_change", args=[result.id])}"
                       style="color: #2563eb; text-decoration: none; font-family: ui-monospace, monospace; font-size: 11px;"
                       title="View/edit archive result">
                        <code>{str(result.id)[-8:]}</code>
                    </a>
                </td>
                <td style="padding: 10px 12px; white-space: nowrap;">
                    <span style="display: inline-block; padding: 3px 10px; border-radius: 12px;
                                 font-size: 11px; font-weight: 600; text-transform: uppercase;
                                 color: {color}; background: {bg};">{status_text}</span>
                </td>
                <td style="padding: 10px 12px; white-space: nowrap; font-size: 20px;" title="{plugin_text}">
                    {icon}
                </td>
                <td class="archive-results-plugin" style="padding: 10px 12px; font-weight: 500; color: #334155;">
                        <a href="{output_link_attr}" target="_blank"
                           style="color: #334155; text-decoration: none;"
                       title="View output fullscreen"
                       onmouseover="this.style.color='#2563eb'; this.style.textDecoration='underline';"
                       onmouseout="this.style.color='#334155'; this.style.textDecoration='none';">
                        {plugin_text}
                    </a>
                </td>
                <td class="archive-results-output" style="padding: 10px 12px; max-width: 280px;">
                    <span onclick="document.getElementById('{row_id}').open = !document.getElementById('{row_id}').open"
                          style="display: block; max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                                 color: #2563eb; text-decoration: none; font-family: ui-monospace, monospace; font-size: 12px; cursor: pointer;"
                          title="Click to expand full output">
                        {output_display}
                    </span>
                </td>
                <td class="archive-results-files" style="padding: 10px 12px; color: #64748b; font-size: 12px; text-align: right;">
                    {output_file_count}
                </td>
                <td class="archive-results-size" style="padding: 10px 12px; color: #64748b; font-size: 12px; text-align: right; white-space: nowrap;">
                    {output_size_display}
                </td>
                <td class="archive-results-completed" style="padding: 10px 12px; color: #64748b; font-size: 12px;">
                    {end_time}
                </td>
                <td style="padding: 10px 12px; white-space: nowrap;">
                    {process_display}
                </td>
                <td style="padding: 10px 12px; white-space: nowrap;">
                    {machine_display}
                </td>
                <td style="padding: 10px 12px; white-space: nowrap; font-family: ui-monospace, monospace; font-size: 11px; color: #64748b;">
                    {version}
                </td>
                <td class="archive-results-actions-cell">
                    <div class="archive-results-actions">
                        <a href="{output_link_attr}" target="_blank"
                           title="View output">📄</a>
                        <a href="{reverse("admin:core_archiveresult_change", args=[result.id])}"
                           title="Edit">✏️</a>
                        {delete_button}
                    </div>
                </td>
            </tr>
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <td colspan="12" style="padding: 0 12px 10px 12px;">
                    <details id="{row_id}" style="margin: 0;">
                        <summary style="cursor: pointer; font-size: 11px; color: #94a3b8; user-select: none;">
                            Details &amp; Output
                        </summary>
                        <div style="margin-top: 8px; padding: 10px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; max-height: 200px; overflow: auto;">
                            <div style="font-size: 11px; color: #64748b; margin-bottom: 8px;">
                                <span style="margin-right: 16px;"><b>ID:</b> <code>{result.id!s}</code></span>
                                <span style="margin-right: 16px;"><b>Version:</b> <code>{version}</code></span>
                                <span style="margin-right: 16px;"><b>PWD:</b> <code>{pwd_text}</code></span>
                            </div>
                            <div style="font-size: 11px; color: #64748b; margin-bottom: 8px;">
                                <b>Output:</b>
                            </div>
                            <pre style="margin: 0; padding: 8px; background: #1e293b; border-radius: 4px; color: #e2e8f0; font-size: 12px; white-space: pre-wrap; word-break: break-all; max-height: 120px; overflow: auto;">{full_output}</pre>
                            <div style="font-size: 11px; color: #64748b; margin-top: 8px;">
                                <b>Command:</b>
                            </div>
                            <div style="position: relative; margin: 0; padding: 8px 56px 8px 8px; background: #1e293b; border-radius: 4px;">
                                <button type="button"
                                        data-command="{cmd_attr}"
                                        onclick="(function(btn){{var text=btn.dataset.command||''; if(navigator.clipboard&&navigator.clipboard.writeText){{navigator.clipboard.writeText(text);}} else {{var ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);}}}})(this); return false;"
                                        style="position: absolute; top: 6px; right: 6px; padding: 2px 8px; border: 0; border-radius: 4px; background: #334155; color: #e2e8f0; font-size: 11px; cursor: pointer;">
                                    Copy
                                </button>
                                <code title="{cmd_attr}" style="display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #e2e8f0; font-size: 11px;">{cmd_str_escaped}</code>
                            </div>
                        </div>
                    </details>
                </td>
            </tr>
        ''')

    total_count = results[0]._inline_total_count
    footer = ""
    if total_count > limit:
        footer = f"""
            <tr data-output-footer>
                <td colspan="12" style="padding: 12px; text-align: center; color: #64748b; font-size: 13px; background: #f8fafc;">
                    Showing {limit} of {total_count} results &nbsp;
                    <a href="/admin/core/archiveresult/?snapshot__id__exact={results[0].snapshot_id if results else ""}"
                       style="color: #2563eb;">View all →</a>
                </td>
            </tr>
        """

    return mark_safe(f"""
        <div style="border: 1px solid #e2e8f0; border-radius: 8px; overflow-x: auto; overflow-y: hidden; background: #fff; width: 100%;">
            <table class="archive-results-table" style="width: 100%; min-width: 1100px; border-collapse: collapse; font-size: 14px;">
                <thead>
                    <tr style="background: #f8fafc; border-bottom: 2px solid #e2e8f0;">
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Details</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Status</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; width: 32px;"></th>
                        <th class="archive-results-plugin" style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Plugin</th>
                        <th class="archive-results-output" style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Output</th>
                        <th class="archive-results-files" style="padding: 10px 12px; text-align: right; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Files</th>
                        <th class="archive-results-size" style="padding: 10px 12px; text-align: right; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">
                            <button type="button" data-output-size-sort style="all: unset; cursor: pointer;">Size ↕</button>
                        </th>
                        <th class="archive-results-completed" style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Completed</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Process</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Machine</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Version</th>
                        <th class="archive-results-actions-cell" style="text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(rows)}
                    {footer}
                </tbody>
            </table>
        </div>
    """)


class ArchiveResultInline(admin.TabularInline):
    name = "Archive Results"
    model = ArchiveResult
    parent_model = Snapshot
    extra = 0
    sort_fields = ("end_ts", "plugin", "output_str", "status", "cmd_version")
    readonly_fields = ("id", "result_id", "completed", "command", "version")
    fields = ("start_ts", "end_ts", *readonly_fields, "plugin", "cmd", "cmd_version", "pwd", "status", "output_str")
    ordering = ("end_ts",)
    show_change_link = True

    def get_parent_object_from_request(self, request):
        resolved = resolve(request.path_info)
        try:
            return self.parent_model.objects.get(pk=resolved.kwargs["object_id"])
        except (self.parent_model.DoesNotExist, ValidationError):
            return None

    @admin.display(
        description="Completed",
        ordering="end_ts",
    )
    def completed(self, obj):
        return format_html('<p style="white-space: nowrap">{}</p>', obj.end_ts.strftime("%Y-%m-%d %H:%M:%S"))

    def result_id(self, obj):
        return format_html(
            '<a href="{}"><code style="font-size: 10px">[{}]</code></a>',
            reverse("admin:core_archiveresult_change", args=(obj.id,)),
            str(obj.id)[:8],
        )

    def command(self, obj):
        return format_html("<small><code>{}</code></small>", " ".join(obj.cmd or []))

    def version(self, obj):
        return format_html("<small><code>{}</code></small>", obj.cmd_version or "-")

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        snapshot = self.get_parent_object_from_request(request)
        base_fields = formset.form.base_fields
        snapshot_output_dir = str(snapshot.output_dir) if snapshot else ""

        # formset.form.base_fields['id'].widget = formset.form.base_fields['id'].hidden_widget()

        # default values for new entries
        base_fields["status"].initial = "succeeded"
        base_fields["start_ts"].initial = timezone.now()
        base_fields["end_ts"].initial = timezone.now()
        base_fields["cmd_version"].initial = "-"
        base_fields["pwd"].initial = snapshot_output_dir
        base_fields["cmd"].initial = '["-"]'
        base_fields["output_str"].initial = "Manually recorded cmd output..."

        if obj is not None:
            # hidden values for existing entries and new entries
            base_fields["start_ts"].widget = base_fields["start_ts"].hidden_widget()
            base_fields["end_ts"].widget = base_fields["end_ts"].hidden_widget()
            base_fields["cmd"].widget = base_fields["cmd"].hidden_widget()
            base_fields["pwd"].widget = base_fields["pwd"].hidden_widget()
            base_fields["cmd_version"].widget = base_fields["cmd_version"].hidden_widget()
        return formset

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return self.readonly_fields
        else:
            return []


class ArchiveResultAdmin(BaseModelAdmin):
    list_select_related = ()
    list_display = (
        "details_link",
        "zip_link",
        "created_at",
        "snapshot_info",
        "tags_inline",
        "status_badge",
        "plugin_with_icon",
        "process_link",
        "machine_link",
        "cmd_str",
        "output_str_display",
    )
    list_display_links = None
    sort_fields = ("id", "created_at", "plugin", "status")
    readonly_fields = (
        "cmd",
        "cmd_version",
        "pwd",
        "cmd_str",
        "admin_actions",
        "snapshot_info",
        "tags_str",
        "created_at",
        "modified_at",
        "output_summary",
        "plugin_with_icon",
        "process_link",
    )
    search_fields = (
        "snapshot__id",
        "snapshot__url",
        "snapshot__tags__name",
        "snapshot__crawl_id",
        "plugin",
        "hook_name",
        "output_str",
        "output_json",
        "process__cmd",
    )
    autocomplete_fields = ("snapshot",)

    fieldsets = (
        (
            "Snapshot",
            {
                "fields": ("snapshot", "snapshot_info", "tags_str", "admin_actions"),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Plugin",
            {
                "fields": ("plugin_with_icon", "process_link", "status"),
                "classes": ("card",),
            },
        ),
        (
            "Timing",
            {
                "fields": ("start_ts", "end_ts", "created_at", "modified_at"),
                "classes": ("card",),
            },
        ),
        (
            "Command",
            {
                "fields": ("cmd", "cmd_str", "cmd_version", "pwd"),
                "classes": ("card",),
            },
        ),
        (
            "Output",
            {
                "fields": ("output_str", "output_json", "output_files", "output_size", "output_mimetypes", "output_summary"),
                "classes": ("card", "wide"),
            },
        ),
    )

    list_filter = ("status", "plugin", "start_ts")
    ordering = ("-start_ts",)
    list_per_page = 50

    paginator = AcceleratedPaginator
    save_on_top = True
    show_full_result_count = False

    actions = ("delete_selected",)

    class Meta:
        verbose_name = "Archive Result"
        verbose_name_plural = "Archive Results"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        self.request = request
        return super().change_view(request, object_id, form_url, extra_context)

    def get_admin_toolbar_actions(self, request, obj):
        if obj is None:
            return []
        self.request = request
        return [
            {
                "label": "View Output",
                "icon": "📄",
                "url": self.get_output_view_url(obj),
                "title": "Open the archived output for this result",
            },
            {
                "label": "Output files",
                "icon": "📁",
                "url": self.get_output_files_url(obj),
                "title": "Browse the output files for this result",
            },
            {
                "label": "Download Zip",
                "icon": "⬇",
                "url": self.get_output_zip_url(obj),
                "kind": "accent",
                "css_classes": "archivebox-zip-button",
                "onclick": "return window.archiveboxHandleZipClick(this, event);",
                "extra_attrs": [("data-loading-label", "Preparing...")],
                "title": "Download all output files as a zip",
            },
            {"label": "Snapshot", "icon": "🗂", "url": self.get_snapshot_view_url(obj), "title": "Open the parent snapshot view"},
        ]

    def changelist_view(self, request, extra_context=None):
        self.request = request
        selected = request.GET.getlist(ACTION_CHECKBOX_NAME)
        if request.method == "GET" and request.GET.get("action") == "delete_selected" and selected:
            if not request.user.is_superuser:
                raise PermissionDenied
            if len(selected) > 100:
                raise SuspiciousOperation("Too many ArchiveResults selected for deletion")
            try:
                queryset = self.get_queryset(request).filter(pk__in=selected)
                if not queryset.exists():
                    snapshot = Snapshot.objects.only("id").filter(pk=request.GET.get("snapshot")).first()
                    return redirect(build_snapshot_url(str(snapshot.id), "index.html", request=request) if snapshot else request.path)
            except (ValidationError, ValueError):
                return redirect(request.path)
            return delete_selected(self, request, queryset)
        handoff_snapshot = (
            request.GET.get("snapshot") if request.method == "POST" and request.GET.get("action") == "delete_selected" else None
        )
        if handoff_snapshot:
            request.GET = request.GET.copy()
            request.GET.clear()
            request.META["QUERY_STRING"] = ""
            try:
                handoff_snapshot = Snapshot.objects.only("id").filter(pk=handoff_snapshot).first()
            except (ValidationError, ValueError):
                handoff_snapshot = None
        saved_list_per_page = self.list_per_page
        self.list_per_page = request.archivebox_config.SNAPSHOTS_PER_PAGE
        try:
            response = super().changelist_view(request, extra_context)
            if (
                handoff_snapshot
                and response.status_code in (301, 302)
                and not ArchiveResult.objects.filter(
                    pk__in=request.POST.getlist(ACTION_CHECKBOX_NAME),
                ).exists()
            ):
                return redirect(build_snapshot_url(str(handoff_snapshot.id), "index.html", request=request))
            return response
        finally:
            self.list_per_page = saved_list_per_page

    def get_queryset(self, request):
        ordering = request.GET.get("o")
        ordering_fields = set()
        if ordering:
            for part in ordering.split("."):
                if not part:
                    continue
                try:
                    idx = abs(int(part)) - 1
                except ValueError:
                    continue
                if 0 <= idx < len(self.list_display):
                    ordering_fields.add(self.list_display[idx])

        qs = (
            super()
            .get_queryset(request)
            .prefetch_related(
                Prefetch(
                    "snapshot",
                    queryset=Snapshot.objects.defer("config", "notes").prefetch_related("crawl__created_by", "tags"),
                ),
                "process__machine",
            )
        )
        if request.resolver_match.url_name == "core_archiveresult_change":
            qs = qs.defer("notes")
        else:
            qs = qs.defer("notes", "output_json")
        if "tags_inline" in ordering_fields:
            qs = qs.annotate(snapshot_first_tag=Min("snapshot__tags__name"))
        return qs

    def get_search_results(self, request, queryset, search_term):
        if not search_term:
            return queryset, False

        queryset = queryset.annotate(
            snapshot_id_text=Cast("snapshot__id", output_field=TextField()),
            snapshot_crawl_id_text=Cast("snapshot__crawl_id", output_field=TextField()),
            output_json_text=Cast("output_json", output_field=TextField()),
            cmd_text=Cast("process__cmd", output_field=TextField()),
        )

        search_bits = [
            bit[1:-1] if len(bit) >= 2 and bit[0] == bit[-1] and bit[0] in {'"', "'"} else bit for bit in smart_split(search_term)
        ]
        search_bits = [bit.strip() for bit in search_bits if bit.strip()]
        if not search_bits:
            return queryset, False

        filters = []
        for bit in search_bits:
            filters.append(
                Q(snapshot_id_text__icontains=bit)
                | Q(snapshot__url__icontains=bit)
                | Q(snapshot__tags__name__icontains=bit)
                | Q(snapshot_crawl_id_text__icontains=bit)
                | Q(plugin__icontains=bit)
                | Q(hook_name__icontains=bit)
                | Q(output_str__icontains=bit)
                | Q(output_json_text__icontains=bit)
                | Q(cmd_text__icontains=bit),
            )

        return queryset.filter(reduce(and_, filters)).distinct(), True

    def get_snapshot_view_url(self, result: ArchiveResult) -> str:
        request = self.request
        return build_snapshot_url(str(result.snapshot_id), request=request, config=request.archivebox_config)

    def get_output_view_url(self, result: ArchiveResult) -> str:
        request = self.request
        config = request.archivebox_config
        output_path = result.embed_path()
        if not output_path:
            output_path = result.plugin or ""
        return build_snapshot_url(str(result.snapshot_id), output_path, request=request, config=config)

    def get_output_files_url(self, result: ArchiveResult) -> str:
        request = self.request
        return f"{build_snapshot_url(str(result.snapshot_id), result.plugin, request=request, config=request.archivebox_config)}/?files=1"

    def get_output_zip_url(self, result: ArchiveResult) -> str:
        return f"{self.get_output_files_url(result)}&download=zip"

    @admin.display(description="Details", ordering="id")
    def details_link(self, result):
        return format_html(
            '<a href="{}"><code>{}</code></a>',
            reverse("admin:core_archiveresult_change", args=[result.id]),
            str(result.id)[-8:],
        )

    @admin.display(description="Zip")
    def zip_link(self, result):
        return format_html(
            '<a href="{}" class="archivebox-zip-button" data-loading-mode="spinner-only" onclick="return window.archiveboxHandleZipClick(this, event);" style="display:inline-flex; align-items:center; justify-content:center; gap:4px; width:48px; min-width:48px; height:24px; padding:0; box-sizing:border-box; border-radius:999px; border:1px solid #bfdbfe; background:#eff6ff; color:#1d4ed8; font-size:11px; font-weight:600; line-height:1; text-decoration:none;"><span class="archivebox-zip-spinner" aria-hidden="true"></span><span class="archivebox-zip-label">⬇ ZIP</span></a>',
            self.get_output_zip_url(result),
        )

    @admin.display(description="")
    def admin_actions(self, result):
        return format_html(
            """
            <div style="display: flex; flex-wrap: wrap; gap: 12px; align-items: center;">
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500;"
                   href="{}">
                    📄 View Output
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500;"
                   href="{}">
                    📁 Output files
                </a>
                <a class="btn archivebox-zip-button" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; color: #1d4ed8; text-decoration: none; font-size: 14px; font-weight: 500;"
                   href="{}"
                   data-loading-label="Preparing..."
                   onclick="return window.archiveboxHandleZipClick(this, event);">
                    <span class="archivebox-zip-spinner" aria-hidden="true"></span>
                    <span class="archivebox-zip-label">⬇ Download Zip</span>
                </a>
                <a class="btn" style="display: inline-flex; align-items: center; gap: 6px; padding: 10px 16px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; color: #334155; text-decoration: none; font-size: 14px; font-weight: 500;"
                   href="{}">
                    🗂 Snapshot
                </a>
            </div>
            """,
            self.get_output_view_url(result),
            self.get_output_files_url(result),
            self.get_output_zip_url(result),
            self.get_snapshot_view_url(result),
        )

    @admin.display(
        description="Snapshot",
        ordering="snapshot__url",
    )
    def snapshot_info(self, result):
        snapshot_id = str(result.snapshot_id)
        request = self.request
        return format_html(
            '<a href="{}"><b><code>[{}]</code></b> &nbsp; {} &nbsp; {}</a><br/>',
            build_snapshot_url(snapshot_id, "index.html", request=request, config=request.archivebox_config),
            snapshot_id[:8],
            result.snapshot.bookmarked_at.strftime("%Y-%m-%d %H:%M"),
            result.snapshot.url[:128],
        )

    @admin.display(
        description="Snapshot Tags",
    )
    def tags_str(self, result):
        return result.snapshot.tags_str()

    @admin.display(description="Tags", ordering="snapshot_first_tag")
    def tags_inline(self, result):
        widget = InlineTagEditorWidget(snapshot_id=str(result.snapshot_id), editable=False)
        tags_html = widget.render(
            name=f"tags_{result.snapshot_id}",
            value=result.snapshot.tags.all(),
            attrs={"id": f"tags_{result.snapshot_id}"},
            snapshot_id=str(result.snapshot_id),
        )
        return mark_safe(f'<span class="tags-inline-editor">{tags_html}</span>')

    @admin.display(description="Status", ordering="status")
    def status_badge(self, result):
        status = result.status or ArchiveResult.StatusChoices.QUEUED
        return format_html(
            '<span class="status-badge {} status-{}">{}</span>',
            status,
            status,
            result.get_status_display() or status,
        )

    @admin.display(description="Plugin", ordering="plugin")
    def plugin_with_icon(self, result):
        icon = get_plugin_icon(result.plugin)
        return format_html(
            '<a href="{}" title="{}">{}</a> <a href="{}"><code>{}</code></a>',
            get_plugin_admin_url(result.plugin),
            result.plugin,
            icon,
            get_plugin_admin_url(result.plugin),
            result.plugin,
        )

    @admin.display(description="Process", ordering="process__pid")
    def process_link(self, result):
        process = result.process_record
        if not process:
            return "-"
        process_label = get_process_link_label(process)
        return format_html(
            '<a href="{}"><code>{}</code></a>',
            reverse("admin:machine_process_change", args=[process.id]),
            process_label,
        )

    @admin.display(description="Machine", ordering="process__machine__hostname")
    def machine_link(self, result):
        process = result.process_record
        if not process or not process.machine_id:
            return "-"
        machine = process.machine
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:machine_machine_change", args=[machine.id]),
            machine.hostname,
        )

    @admin.display(description="Command")
    def cmd_str(self, result):
        request = self.request
        display_cmd = build_abx_dl_display_command(result)
        replay_cmd = build_abx_dl_replay_command(result, config=request.archivebox_config)
        return format_html(
            """
            <div style="position: relative; width: 100%; max-width: 100%; overflow: hidden; box-sizing: border-box;">
                <button type="button"
                        data-command="{}"
                        onclick="(function(btn){{var text=btn.dataset.command||''; if(navigator.clipboard&&navigator.clipboard.writeText){{navigator.clipboard.writeText(text);}} else {{var ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);}}}})(this); return false;"
                        style="position: absolute; top: 6px; right: 6px; z-index: 1; padding: 2px 8px; border: 0; border-radius: 4px; background: #e2e8f0; color: #334155; font-size: 11px; cursor: pointer;">
                    Copy
                </button>
                <code title="{}" style="display: block; width: 100%; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 8px 56px 8px 8px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 11px; box-sizing: border-box;">
                    {}
                </code>
            </div>
            """,
            replay_cmd,
            replay_cmd,
            display_cmd,
        )

    def output_display(self, result):
        request = self.request
        config = request.archivebox_config
        # Determine output link path - use embed_path() which checks output_files
        embed_path = result.embed_path()
        output_path = embed_path if (result.status == "succeeded" and embed_path) else "index.html"
        snapshot_id = str(result.snapshot_id)
        return format_html(
            '<a href="{}" class="output-link">↗️</a><pre>{}</pre>',
            build_snapshot_url(snapshot_id, output_path, request=request, config=config),
            result.output_str_for_display(),
        )

    @admin.display(description="Output", ordering="output_str")
    def output_str_display(self, result):
        output_text = str(result.output_str_for_display() or "").strip()
        if not output_text:
            return "-"

        request = self.request
        live_path = result.embed_path()
        if live_path:
            return format_html(
                '<a href="{}" title="{}"><code>{}</code></a>',
                build_snapshot_url(str(result.snapshot_id), live_path, request=request, config=request.archivebox_config),
                output_text,
                output_text,
            )

        return format_html(
            '<span title="{}">{}</span>',
            output_text,
            output_text,
        )

    def output_summary(self, result):
        snapshot_dir = Path(result.snapshot.output_dir)
        output_html = format_html(
            '<pre style="display: inline-block">{}</pre><br/>',
            result.output_str_for_display(),
        )
        snapshot_id = str(result.snapshot_id)
        request = self.request
        output_html += format_html(
            '<a href="{}#all">See result files ...</a><br/><pre><code>',
            build_snapshot_url(snapshot_id, "index.html", request=request, config=request.archivebox_config),
        )
        embed_path = result.embed_path() or ""
        path_from_embed = snapshot_dir / (embed_path or "")
        output_html += format_html(
            '<i style="padding: 1px">{}</i><b style="padding-right: 20px">/</b><i>{}</i><br/><hr/>',
            str(snapshot_dir),
            str(embed_path),
        )
        if os.access(path_from_embed, os.R_OK):
            root_dir = str(path_from_embed)
        else:
            root_dir = str(snapshot_dir)

        for root, dirs, files in os.walk(root_dir):
            depth = root.replace(root_dir, "").count(os.sep) + 1
            if depth > 2:
                continue
            indent = " " * 4 * (depth)
            output_html += format_html('<b style="padding: 1px">{}{}/</b><br/>', indent, os.path.basename(root))
            indentation_str = " " * 4 * (depth + 1)
            for filename in sorted(files):
                is_hidden = filename.startswith(".")
                output_html += format_html(
                    '<span style="opacity: {}.2">{}{}</span><br/>',
                    int(not is_hidden),
                    indentation_str,
                    filename.strip(),
                )

        return output_html + mark_safe("</code></pre>")


def register_admin(admin_site):
    admin_site.register(ArchiveResult, ArchiveResultAdmin)
