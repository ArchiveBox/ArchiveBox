__package__ = "archivebox.core"

import html
import json
import os
import shlex
from pathlib import Path
from urllib.parse import quote
from functools import reduce
from operator import and_

from django.contrib import admin
from django.db.models import Min, Q, TextField
from django.db.models.functions import Cast
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.core.exceptions import ValidationError
from django.urls import reverse, resolve
from django.utils import timezone
from django.utils.text import smart_split

from archivebox.config import DATA_DIR
from archivebox.config.common import SERVER_CONFIG
from archivebox.misc.paginators import AcceleratedPaginator
from archivebox.base_models.admin import BaseModelAdmin
from archivebox.hooks import get_plugin_icon
from archivebox.core.host_utils import build_snapshot_url
from archivebox.core.widgets import InlineTagEditorWidget
from archivebox.core.views import LIVE_PLUGIN_BASE_URL
from archivebox.machine.env_utils import env_to_shell_exports


from archivebox.core.models import ArchiveResult, Snapshot


def _quote_shell_string(value: str) -> str:
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def _get_replay_source_url(result: ArchiveResult) -> str:
    process = getattr(result, "process", None)
    return str(getattr(process, "url", None) or result.snapshot.url or "")


def build_abx_dl_display_command(result: ArchiveResult) -> str:
    source_url = _get_replay_source_url(result)
    plugin_name = str(result.plugin or "").strip()
    if not plugin_name and not source_url:
        return "abx-dl"
    if not source_url:
        return f"abx-dl --plugins={plugin_name}"
    return f"abx-dl --plugins={plugin_name} {_quote_shell_string(source_url)}"


def build_abx_dl_replay_command(result: ArchiveResult) -> str:
    display_command = build_abx_dl_display_command(result)
    process = getattr(result, "process", None)
    env_items = env_to_shell_exports(getattr(process, "env", None) or {})
    snapshot_dir = shlex.quote(str(result.snapshot_dir))
    if env_items:
        return f"cd {snapshot_dir}; env {env_items} {display_command}"
    return f"cd {snapshot_dir}; {display_command}"


def get_plugin_admin_url(plugin_name: str) -> str:
    from archivebox.hooks import BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR, iter_plugin_dirs

    plugin_dir = next((path.resolve() for path in iter_plugin_dirs() if path.name == plugin_name), None)
    if plugin_dir:
        builtin_root = BUILTIN_PLUGINS_DIR.resolve()
        if plugin_dir.is_relative_to(builtin_root):
            return f"{LIVE_PLUGIN_BASE_URL}builtin.{quote(plugin_name)}/"

        user_root = USER_PLUGINS_DIR.resolve()
        if plugin_dir.is_relative_to(user_root):
            return f"{LIVE_PLUGIN_BASE_URL}user.{quote(plugin_name)}/"

    return f"{LIVE_PLUGIN_BASE_URL}builtin.{quote(plugin_name)}/"


def render_archiveresults_list(archiveresults_qs, limit=50):
    """Render a nice inline list view of archive results with status, plugin, output, and actions."""

    result_ids = list(archiveresults_qs.order_by("plugin").values_list("pk", flat=True)[:limit])
    if not result_ids:
        return mark_safe('<div style="color: #64748b; font-style: italic; padding: 16px 0;">No Archive Results yet...</div>')

    results_by_id = {
        result.pk: result
        for result in ArchiveResult.objects.filter(pk__in=result_ids).select_related("snapshot", "process", "process__machine")
    }
    results = [results_by_id[result_id] for result_id in result_ids if result_id in results_by_id]

    if not results:
        return mark_safe('<div style="color: #64748b; font-style: italic; padding: 16px 0;">No Archive Results yet...</div>')

    # Status colors
    status_colors = {
        "succeeded": ("#166534", "#dcfce7"),  # green
        "failed": ("#991b1b", "#fee2e2"),  # red
        "queued": ("#6b7280", "#f3f4f6"),  # gray
        "started": ("#92400e", "#fef3c7"),  # amber
        "backoff": ("#92400e", "#fef3c7"),
        "skipped": ("#475569", "#f1f5f9"),
        "noresults": ("#475569", "#f1f5f9"),
    }

    rows = []
    for idx, result in enumerate(results):
        status = result.status or "queued"
        color, bg = status_colors.get(status, ("#6b7280", "#f3f4f6"))
        output_files = result.output_files or {}
        if isinstance(output_files, dict):
            output_file_count = len(output_files)
        elif isinstance(output_files, (list, tuple, set)):
            output_file_count = len(output_files)
        elif isinstance(output_files, str):
            try:
                parsed = json.loads(output_files)
                output_file_count = len(parsed) if isinstance(parsed, (dict, list, tuple, set)) else 0
            except Exception:
                output_file_count = 0
        else:
            output_file_count = 0

        # Get plugin icon
        icon = get_plugin_icon(result.plugin)

        # Format timestamp
        end_time = result.end_ts.strftime("%Y-%m-%d %H:%M:%S") if result.end_ts else "-"

        process_display = "-"
        if result.process_id and result.process:
            process_display = f'''
                <a href="{reverse("admin:machine_process_change", args=[result.process_id])}"
                   style="color: #2563eb; text-decoration: none; font-family: ui-monospace, monospace; font-size: 12px;"
                   title="View process">{result.process.pid or "-"}</a>
            '''

        machine_display = "-"
        if result.process_id and result.process and result.process.machine_id:
            machine_display = f'''
                <a href="{reverse("admin:machine_machine_change", args=[result.process.machine_id])}"
                   style="color: #2563eb; text-decoration: none; font-size: 12px;"
                   title="View machine">{result.process.machine.hostname}</a>
            '''

        # Truncate output for display
        full_output = result.output_str or "-"
        output_display = full_output[:60]
        if len(full_output) > 60:
            output_display += "..."

        display_cmd = build_abx_dl_display_command(result)
        replay_cmd = build_abx_dl_replay_command(result)
        cmd_str_escaped = html.escape(display_cmd)
        cmd_attr = html.escape(replay_cmd, quote=True)

        # Build output link - use embed_path() which checks output_files first
        embed_path = result.embed_path() if hasattr(result, "embed_path") else None
        snapshot_id = str(getattr(result, "snapshot_id", ""))
        if embed_path and result.status == "succeeded":
            output_link = build_snapshot_url(snapshot_id, embed_path)
        else:
            output_link = build_snapshot_url(snapshot_id, "")

        # Get version - try cmd_version field
        version = result.cmd_version if result.cmd_version else "-"

        # Unique ID for this row's expandable output
        row_id = f"output_{idx}_{str(result.id)[:8]}"

        rows.append(f'''
            <tr style="border-bottom: 1px solid #f1f5f9; transition: background 0.15s;" onmouseover="this.style.background='#f8fafc'" onmouseout="this.style.background='transparent'">
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
                                 color: {color}; background: {bg};">{status}</span>
                </td>
                <td style="padding: 10px 12px; white-space: nowrap; font-size: 20px;" title="{result.plugin}">
                    {icon}
                </td>
                <td style="padding: 10px 12px; font-weight: 500; color: #334155;">
                        <a href="{output_link}" target="_blank"
                           style="color: #334155; text-decoration: none;"
                       title="View output fullscreen"
                       onmouseover="this.style.color='#2563eb'; this.style.textDecoration='underline';"
                       onmouseout="this.style.color='#334155'; this.style.textDecoration='none';">
                        {result.plugin}
                    </a>
                </td>
                <td style="padding: 10px 12px; max-width: 280px;">
                    <span onclick="document.getElementById('{row_id}').open = !document.getElementById('{row_id}').open"
                          style="color: #2563eb; text-decoration: none; font-family: ui-monospace, monospace; font-size: 12px; cursor: pointer;"
                          title="Click to expand full output">
                        {output_display}
                    </span>
                </td>
                <td style="padding: 10px 12px; white-space: nowrap; color: #64748b; font-size: 12px; text-align: right;">
                    {output_file_count}
                </td>
                <td style="padding: 10px 12px; white-space: nowrap; color: #64748b; font-size: 12px;">
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
                <td style="padding: 10px 8px; white-space: nowrap;">
                    <div style="display: flex; gap: 4px;">
                        <a href="{output_link}" target="_blank"
                           style="padding: 4px 8px; background: #f1f5f9; border-radius: 4px; color: #475569; text-decoration: none; font-size: 11px;"
                           title="View output">📄</a>
                        <a href="{reverse("admin:core_archiveresult_change", args=[result.id])}"
                           style="padding: 4px 8px; background: #f1f5f9; border-radius: 4px; color: #475569; text-decoration: none; font-size: 11px;"
                           title="Edit">✏️</a>
                    </div>
                </td>
            </tr>
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <td colspan="11" style="padding: 0 12px 10px 12px;">
                    <details id="{row_id}" style="margin: 0;">
                        <summary style="cursor: pointer; font-size: 11px; color: #94a3b8; user-select: none;">
                            Details &amp; Output
                        </summary>
                        <div style="margin-top: 8px; padding: 10px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; max-height: 200px; overflow: auto;">
                            <div style="font-size: 11px; color: #64748b; margin-bottom: 8px;">
                                <span style="margin-right: 16px;"><b>ID:</b> <code>{str(result.id)}</code></span>
                                <span style="margin-right: 16px;"><b>Version:</b> <code>{version}</code></span>
                                <span style="margin-right: 16px;"><b>PWD:</b> <code>{result.pwd or "-"}</code></span>
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

    total_count = archiveresults_qs.count()
    footer = ""
    if total_count > limit:
        footer = f"""
            <tr>
                <td colspan="11" style="padding: 12px; text-align: center; color: #64748b; font-size: 13px; background: #f8fafc;">
                    Showing {limit} of {total_count} results &nbsp;
                    <a href="/admin/core/archiveresult/?snapshot__id__exact={results[0].snapshot_id if results else ""}"
                       style="color: #2563eb;">View all →</a>
                </td>
            </tr>
        """

    return mark_safe(f"""
        <div style="border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; background: #fff; width: 100%;">
            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                <thead>
                    <tr style="background: #f8fafc; border-bottom: 2px solid #e2e8f0;">
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Details</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Status</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; width: 32px;"></th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Plugin</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Output</th>
                        <th style="padding: 10px 12px; text-align: right; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Files</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Completed</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Process</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Machine</th>
                        <th style="padding: 10px 12px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Version</th>
                        <th style="padding: 10px 8px; text-align: left; font-weight: 600; color: #475569; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">Actions</th>
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
    name = "Archive Results Log"
    model = ArchiveResult
    parent_model = Snapshot
    # fk_name = 'snapshot'
    extra = 0
    sort_fields = ("end_ts", "plugin", "output_str", "status", "cmd_version")
    readonly_fields = ("id", "result_id", "completed", "command", "version")
    fields = ("start_ts", "end_ts", *readonly_fields, "plugin", "cmd", "cmd_version", "pwd", "status", "output_str")
    # exclude = ('id',)
    ordering = ("end_ts",)
    show_change_link = True
    # # classes = ['collapse']

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
        form_class = getattr(formset, "form", None)
        base_fields = getattr(form_class, "base_fields", {})
        snapshot_output_dir = str(snapshot.output_dir) if snapshot else ""

        # import ipdb; ipdb.set_trace()
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
        "admin_actions",
        "cmd",
        "cmd_version",
        "pwd",
        "cmd_str",
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
    autocomplete_fields = ["snapshot"]

    fieldsets = (
        (
            "Actions",
            {
                "fields": ("admin_actions",),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Snapshot",
            {
                "fields": ("snapshot", "snapshot_info", "tags_str"),
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
    ordering = ["-start_ts"]
    list_per_page = SERVER_CONFIG.SNAPSHOTS_PER_PAGE

    paginator = AcceleratedPaginator
    save_on_top = True

    actions = ["delete_selected"]

    class Meta:
        verbose_name = "Archive Result"
        verbose_name_plural = "Archive Results"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        self.request = request
        return super().change_view(request, object_id, form_url, extra_context)

    def changelist_view(self, request, extra_context=None):
        self.request = request
        return super().changelist_view(request, extra_context)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("snapshot", "process")
            .prefetch_related("snapshot__tags")
            .annotate(snapshot_first_tag=Min("snapshot__tags__name"))
        )

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
        return build_snapshot_url(str(result.snapshot_id), request=getattr(self, "request", None))

    def get_output_view_url(self, result: ArchiveResult) -> str:
        output_path = result.embed_path() if hasattr(result, "embed_path") else None
        if not output_path:
            output_path = result.plugin or ""
        return build_snapshot_url(str(result.snapshot_id), output_path, request=getattr(self, "request", None))

    def get_output_files_url(self, result: ArchiveResult) -> str:
        return f"{build_snapshot_url(str(result.snapshot_id), result.plugin, request=getattr(self, 'request', None))}/?files=1"

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

    @admin.display(
        description="Snapshot",
        ordering="snapshot__url",
    )
    def snapshot_info(self, result):
        snapshot_id = str(result.snapshot_id)
        return format_html(
            '<a href="{}"><b><code>[{}]</code></b> &nbsp; {} &nbsp; {}</a><br/>',
            build_snapshot_url(snapshot_id, "index.html"),
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
        if not result.process_id:
            return "-"
        process_label = result.process.pid if result.process and result.process.pid else "-"
        return format_html(
            '<a href="{}"><code>{}</code></a>',
            reverse("admin:machine_process_change", args=[result.process_id]),
            process_label,
        )

    @admin.display(description="Machine", ordering="process__machine__hostname")
    def machine_link(self, result):
        if not result.process_id or not result.process or not result.process.machine_id:
            return "-"
        machine = result.process.machine
        return format_html(
            '<a href="{}"><code>{}</code> {}</a>',
            reverse("admin:machine_machine_change", args=[machine.id]),
            str(machine.id)[:8],
            machine.hostname,
        )

    @admin.display(description="Command")
    def cmd_str(self, result):
        display_cmd = build_abx_dl_display_command(result)
        replay_cmd = build_abx_dl_replay_command(result)
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
        # Determine output link path - use embed_path() which checks output_files
        embed_path = result.embed_path() if hasattr(result, "embed_path") else None
        output_path = embed_path if (result.status == "succeeded" and embed_path) else "index.html"
        snapshot_id = str(result.snapshot_id)
        return format_html(
            '<a href="{}" class="output-link">↗️</a><pre>{}</pre>',
            build_snapshot_url(snapshot_id, output_path),
            result.output_str,
        )

    @admin.display(description="Output", ordering="output_str")
    def output_str_display(self, result):
        output_text = str(result.output_str or "").strip()
        if not output_text:
            return "-"

        live_path = result.embed_path() if hasattr(result, "embed_path") else None
        if live_path:
            return format_html(
                '<a href="{}" title="{}"><code>{}</code></a>',
                build_snapshot_url(str(result.snapshot_id), live_path),
                output_text,
                output_text,
            )

        return format_html(
            '<span title="{}">{}</span>',
            output_text,
            output_text,
        )

    @admin.display(description="")
    def admin_actions(self, result):
        return format_html(
            """
            <div style="display:flex; flex-wrap:wrap; gap:12px; align-items:center;">
                <a class="btn" style="display:inline-flex; align-items:center; gap:6px; padding:10px 16px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; color:#334155; text-decoration:none; font-size:14px; font-weight:500; transition:all 0.15s;"
                   href="{}"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    📄 View Output
                </a>
                <a class="btn" style="display:inline-flex; align-items:center; gap:6px; padding:10px 16px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; color:#334155; text-decoration:none; font-size:14px; font-weight:500; transition:all 0.15s;"
                   href="{}"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    📁 Output files
                </a>
                <a class="btn archivebox-zip-button" style="display:inline-flex; align-items:center; gap:6px; padding:10px 16px; background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; color:#1d4ed8; text-decoration:none; font-size:14px; font-weight:500; transition:all 0.15s;"
                   href="{}"
                   data-loading-label="Preparing..."
                   onclick="return window.archiveboxHandleZipClick(this, event);"
                   onmouseover="this.style.background='#dbeafe'; this.style.borderColor='#93c5fd';"
                   onmouseout="this.style.background='#eff6ff'; this.style.borderColor='#bfdbfe';">
                    <span class="archivebox-zip-spinner" aria-hidden="true"></span>
                    <span class="archivebox-zip-label">⬇ Download Zip</span>
                </a>
                <a class="btn" style="display:inline-flex; align-items:center; gap:6px; padding:10px 16px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; color:#334155; text-decoration:none; font-size:14px; font-weight:500; transition:all 0.15s;"
                   href="{}"
                   onmouseover="this.style.background='#f1f5f9'; this.style.borderColor='#cbd5e1';"
                   onmouseout="this.style.background='#f8fafc'; this.style.borderColor='#e2e8f0';">
                    🗂 Snapshot
                </a>
            </div>
            """,
            self.get_output_view_url(result),
            self.get_output_files_url(result),
            self.get_output_zip_url(result),
            self.get_snapshot_view_url(result),
        )

    def output_summary(self, result):
        snapshot_dir = Path(DATA_DIR) / str(result.pwd).split("data/", 1)[-1]
        output_html = format_html(
            '<pre style="display: inline-block">{}</pre><br/>',
            result.output_str,
        )
        snapshot_id = str(result.snapshot_id)
        output_html += format_html(
            '<a href="{}#all">See result files ...</a><br/><pre><code>',
            build_snapshot_url(snapshot_id, "index.html"),
        )
        embed_path = result.embed_path() if hasattr(result, "embed_path") else ""
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

        # print(root_dir, str(list(os.walk(root_dir))))

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
