__package__ = "archivebox.machine"

import json
import shlex
from pathlib import Path

from django.contrib import admin, messages
from django.contrib.admin.options import IncorrectLookupParameters
from django.contrib.admin.views.main import ChangeList
from django.db import DatabaseError
from django.db.models import DurationField, ExpressionWrapper, F, Prefetch
from django.db.models.functions import Coalesce, Now
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.html import format_html
from django_object_actions import action

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin
from archivebox.machine.env_util import env_to_dotenv_text
from archivebox.machine.forms import MachineAdminForm
from archivebox.machine.models import Binary, Machine, NetworkInterface, Process
from archivebox.misc.logging_util import printable_filesize
from archivebox.misc.paginators import AcceleratedPaginator


def _render_copy_block(text: str, *, multiline: bool = False):
    if multiline:
        return format_html(
            """
            <div style="position: relative; width: 100%; max-width: 100%; overflow: hidden; box-sizing: border-box;">
                <button type="button"
                        data-command="{}"
                        onclick="(function(btn){{var text=btn.dataset.command||''; if(navigator.clipboard&&navigator.clipboard.writeText){{navigator.clipboard.writeText(text);}} else {{var ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);}}}})(this); return false;"
                        style="position: absolute; top: 6px; right: 6px; z-index: 1; padding: 2px 8px; border: 0; border-radius: 4px; background: #e2e8f0; color: #334155; font-size: 11px; cursor: pointer;">
                    Copy
                </button>
                <pre title="{}" style="display: block; width: 100%; max-width: 100%; overflow: auto; max-height: 300px; margin: 0; padding: 8px 56px 8px 8px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; font-size: 11px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; box-sizing: border-box;">{}</pre>
            </div>
            """,
            text,
            text,
            text,
        )
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
        text,
        text,
        text,
    )


def _format_process_duration_seconds(started_at, ended_at) -> str:
    if not started_at:
        return "-"

    end_time = ended_at or timezone.now()
    seconds = max((end_time - started_at).total_seconds(), 0.0)
    if seconds < 1:
        return f"{seconds:.2f}s"
    if seconds < 10 and seconds != int(seconds):
        return f"{seconds:.1f}s"
    return f"{int(seconds)}s"


class MachineAdmin(ConfigEditorMixin, BaseModelAdmin):
    config_includes_machine_settings = True
    reserve_sqlite_config_writer = True
    form = MachineAdminForm
    change_form_template = "admin/machine/machine/change_form.html"
    list_display = (
        "id_display",
        "created_at",
        "hostname",
        "ips",
        "os_platform",
        "hw_in_docker",
        "hw_in_vm",
        "hw_manufacturer",
        "hw_product",
        "os_arch",
        "os_family",
        "os_release",
        "hw_uuid",
        "health_display",
    )
    sort_fields = (
        "id",
        "created_at",
        "hostname",
        "ips",
        "os_platform",
        "hw_in_docker",
        "hw_in_vm",
        "hw_manufacturer",
        "hw_product",
        "os_arch",
        "os_family",
        "os_release",
        "hw_uuid",
    )
    search_fields = (
        "id",
        "guid",
        "hostname",
        "networkinterface__ip_public",
        "networkinterface__ip_local",
        "hw_manufacturer",
        "hw_product",
        "hw_uuid",
        "os_platform",
        "os_family",
        "os_arch",
        "os_release",
        "os_kernel",
    )

    readonly_fields = ("guid", "created_at", "modified_at", "ips")

    fieldsets = (
        (
            "Identity",
            {
                "fields": ("hostname", "guid", "ips"),
                "classes": ("card",),
            },
        ),
        (
            "Hardware",
            {
                "fields": ("hw_manufacturer", "hw_product", "hw_uuid", "hw_in_docker", "hw_in_vm"),
                "classes": ("card",),
            },
        ),
        (
            "Operating System",
            {
                "fields": ("os_platform", "os_family", "os_arch", "os_kernel", "os_release"),
                "classes": ("card",),
            },
        ),
        (
            "Statistics",
            {
                "fields": ("stats", "num_uses_succeeded", "num_uses_failed"),
                "classes": ("card",),
            },
        ),
        (
            "Additional configuration",
            {
                "fields": ("config",),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "modified_at"),
                "classes": ("card",),
            },
        ),
    )

    list_filter = ("hw_in_docker", "hw_in_vm", "os_arch", "os_family", "os_platform")
    ordering = ("-created_at",)
    list_per_page = 100
    actions = ("delete_selected",)

    @admin.display(description="Public IP", ordering="networkinterface__ip_public")
    def ips(self, machine):
        return format_html(
            '<a href="/admin/machine/networkinterface/?q={}"><b><code>{}</code></b></a>',
            machine.id,
            ", ".join(machine.networkinterface_set.values_list("ip_public", flat=True)),
        )

    @admin.display(description="Health", ordering="health")
    def health_display(self, obj):
        h = obj.health
        color = "green" if h >= 80 else "orange" if h >= 50 else "red"
        return format_html('<span style="color: {};">{}</span>', color, h)

    @admin.display(description="ID", ordering="id")
    def id_display(self, machine):
        # Highlight the row representing the machine that ``Machine.current()``
        # resolves to in this process — that's the one whose ``config`` is
        # actually being applied at runtime. Important to surface here because
        # a collection can accumulate stale Machine rows from prior hosts (VM
        # snapshots, container rebuilds, hostname changes), and editing the
        # wrong one silently produces "I set BASE_URL but it didn't stick."
        from archivebox.machine.models import Machine

        try:
            current_id = str(Machine.current().pk)
        except (DatabaseError, RuntimeError, TypeError, ValueError):
            current_id = None

        machine_id = str(machine.pk)
        short_id = machine_id[:8]
        if current_id and machine_id == current_id:
            return format_html(
                '<span style="display:inline-block;background:#16a34a;color:#fff;'
                "padding:1px 6px;border-radius:3px;font-weight:800;font-size:11px;"
                'margin-right:6px;letter-spacing:0.3px;">★ CURRENT</span>'
                '<code style="font-weight:700;">{}</code>',
                short_id,
            )
        return format_html(
            '<code style="color:#888;">{}</code>',
            short_id,
        )


class NetworkInterfaceAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "created_at",
        "machine_info",
        "ip_public",
        "dns_server",
        "isp",
        "country",
        "region",
        "city",
        "iface",
        "ip_local",
        "mac_address",
        "health_display",
    )
    sort_fields = (
        "id",
        "created_at",
        "machine_info",
        "ip_public",
        "dns_server",
        "isp",
        "country",
        "region",
        "city",
        "iface",
        "ip_local",
        "mac_address",
    )
    search_fields = (
        "id",
        "machine__id",
        "iface",
        "ip_public",
        "ip_local",
        "mac_address",
        "dns_server",
        "hostname",
        "isp",
        "city",
        "region",
        "country",
    )

    readonly_fields = ("machine", "created_at", "modified_at", "mac_address", "ip_public", "ip_local", "dns_server")

    fieldsets = (
        (
            "Machine",
            {
                "fields": ("machine",),
                "classes": ("card",),
            },
        ),
        (
            "Network",
            {
                "fields": ("iface", "ip_public", "ip_local", "mac_address", "dns_server"),
                "classes": ("card",),
            },
        ),
        (
            "Location",
            {
                "fields": ("hostname", "isp", "city", "region", "country"),
                "classes": ("card",),
            },
        ),
        (
            "Usage",
            {
                "fields": ("num_uses_succeeded", "num_uses_failed"),
                "classes": ("card",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "modified_at"),
                "classes": ("card",),
            },
        ),
    )

    list_filter = ("isp", "country", "region")
    ordering = ("-created_at",)
    list_per_page = 100
    actions = ("delete_selected",)

    @admin.display(description="Machine", ordering="machine__id")
    def machine_info(self, iface):
        return format_html(
            '<a href="/admin/machine/machine/{}/change"><b><code>[{}]</code></b> &nbsp; {}</a>',
            iface.machine.id,
            str(iface.machine.id)[:8],
            iface.machine.hostname,
        )

    @admin.display(description="Health", ordering="health")
    def health_display(self, obj):
        h = obj.health
        color = "green" if h >= 80 else "orange" if h >= 50 else "red"
        return format_html('<span style="color: {};">{}</span>', color, h)


class BinaryAdmin(BaseModelAdmin):
    list_display = ("id", "created_at", "machine_info", "name", "binprovider", "version", "abspath", "sha256", "status", "health_display")
    sort_fields = ("id", "created_at", "machine_info", "name", "binprovider", "version", "abspath", "sha256", "status")
    search_fields = ("id", "machine__id", "name", "binprovider", "version", "abspath", "sha256")

    readonly_fields = ("created_at", "modified_at", "output_dir")

    fieldsets = (
        (
            "Binary Info",
            {
                "fields": ("name", "binproviders", "binprovider", "overrides"),
                "classes": ("card",),
            },
        ),
        (
            "Location",
            {
                "fields": ("machine", "abspath"),
                "classes": ("card",),
            },
        ),
        (
            "Version",
            {
                "fields": ("version", "sha256"),
                "classes": ("card",),
            },
        ),
        (
            "State",
            {
                "fields": ("status", "retry_at", "output_dir"),
                "classes": ("card",),
            },
        ),
        (
            "Usage",
            {
                "fields": ("num_uses_succeeded", "num_uses_failed"),
                "classes": ("card",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "modified_at"),
                "classes": ("card",),
            },
        ),
    )

    list_filter = ("name", "binprovider", "status", "machine_id")
    ordering = ("-created_at",)
    list_per_page = 100
    actions = ("delete_selected",)

    @admin.display(description="Machine", ordering="machine__id")
    def machine_info(self, binary):
        return format_html(
            '<a href="/admin/machine/machine/{}/change"><b><code>[{}]</code></b> &nbsp; {}</a>',
            binary.machine.id,
            str(binary.machine.id)[:8],
            binary.machine.hostname,
        )

    @admin.display(description="Health", ordering="health")
    def health_display(self, obj):
        h = obj.health
        color = "green" if h >= 80 else "orange" if h >= 50 else "red"
        return format_html('<span style="color: {};">{}</span>', color, h)


class ProcessExitCodeFilter(admin.AllValuesFieldListFilter):
    """Keep exact exit-code URLs without enumerating the process history."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        common_codes = {0, 1, 2, 124, 125, 126, 127, 130, 137, 143}
        for value in self.lookup_val or ():
            try:
                common_codes.add(int(value))
            except (TypeError, ValueError):
                pass
        self.lookup_choices = (*sorted(common_codes), None)


class ProcessChangeList(ChangeList):
    def get_results(self, request):
        if request.method != "GET" or (request.GET.keys() - {"p"}):
            return super().get_results(request)

        # Match the Snapshot changelist's bounded first render: a lookahead
        # row supplies Next without counting every stored Process. Keep the
        # stock exact paginator for every explicit filter or action.
        if self.page_num < 1:
            raise IncorrectLookupParameters
        start = (self.page_num - 1) * self.list_per_page
        rows = list(self.queryset[start : start + self.list_per_page + 1])
        if start and not rows:
            raise IncorrectLookupParameters
        observed = start + len(rows)
        self.queryset.query._archivebox_count_hint = observed
        super().get_results(request)

        has_next = len(rows) > self.list_per_page
        self.result_list = rows[: self.list_per_page]
        self.result_count_exact = not has_next
        self.display_result_count = observed
        self.next_page_url = self.get_query_string({"p": self.page_num + 1}) if has_next else None
        self.previous_page_url = self.get_query_string({"p": self.page_num - 1}) if self.page_num > 1 else None


class ProcessAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "created_at",
        "machine_info",
        "archiveresult_link",
        "snapshot_link",
        "crawl_link",
        "cmd_str",
        "status_badge",
        "duration_display",
        "exit_code",
        "pid",
        "output_summary",
        "binary_info",
    )
    sort_fields = (
        "id",
        "created_at",
        "machine_info",
        "archiveresult_link",
        "snapshot_link",
        "crawl_link",
        "cmd_str",
        "status_badge",
        "duration_display",
        "exit_code",
        "pid",
        "output_summary",
        "binary_info",
    )
    search_fields = ("id", "machine__id", "binary__name", "cmd", "pwd", "stdout", "stderr", "env")

    readonly_fields = (
        "created_at",
        "modified_at",
        "machine",
        "binary_link",
        "iface_link",
        "archiveresult_link",
        "snapshot_link",
        "crawl_link",
        "cmd_display",
        "env_display",
        "stdout_display",
        "stderr_display",
        "archiveresult_output_display",
        "timeout",
        "pid",
        "exit_code",
        "url",
        "started_at",
        "ended_at",
        "duration_display",
    )

    fieldsets = (
        (
            "Process Info",
            {
                "fields": ("machine", "archiveresult_link", "snapshot_link", "crawl_link", "status", "retry_at"),
                "classes": ("card",),
            },
        ),
        (
            "Command",
            {
                "fields": ("cmd_display", "pwd", "env_display", "timeout"),
                "classes": ("card", "wide"),
            },
        ),
        (
            "Execution",
            {
                "fields": ("binary_link", "iface_link", "pid", "exit_code", "url"),
                "classes": ("card",),
            },
        ),
        (
            "Timing",
            {
                "fields": ("started_at", "ended_at", "duration_display"),
                "classes": ("card",),
            },
        ),
        (
            "Output",
            {
                "fields": ("stdout_display", "stderr_display", "archiveresult_output_display"),
                "classes": ("card", "wide", "collapse"),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "modified_at"),
                "classes": ("card",),
            },
        ),
    )

    list_filter = ("status", ("exit_code", ProcessExitCodeFilter), "machine_id")
    show_full_result_count = False
    ordering = ("-created_at",)
    list_per_page = 100
    paginator = AcceleratedPaginator
    actions = ("kill_processes", "delete_selected")
    change_actions = ("kill_process",)

    def get_changelist(self, request, **kwargs):
        return ProcessChangeList

    def get_queryset(self, request):
        queryset = (
            super()
            .get_queryset(request)
            .select_related("binary", "iface", "archiveresult__snapshot__crawl")
            .annotate(
                runtime_sort=ExpressionWrapper(
                    Coalesce(F("ended_at"), Now()) - F("started_at"),
                    output_field=DurationField(),
                ),
            )
        )

        # List rows never render log bodies. Keep search predicates intact,
        # and leave detail/action querysets fully loaded for their consumers.
        if (
            request.method == "GET"
            and request.resolver_match is not None
            and request.resolver_match.url_name == "machine_process_changelist"
        ):
            # The Machine INNER JOIN made SQLite walk per-machine Process
            # indexes and sort millions of rows just to display the newest 100.
            # Fetch their labels after pagination so the time index can drive it.
            return queryset.defer(
                "stdout",
                "stderr",
                "archiveresult__snapshot__crawl__urls",
                "archiveresult__snapshot__crawl__config",
            ).prefetch_related(
                Prefetch("machine", queryset=Machine.objects.only("id", "hostname")),
            )
        return queryset.select_related("machine")

    def _terminate_processes(self, request, processes):
        terminated = 0
        skipped = 0

        for process in processes:
            if process.status == Process.StatusChoices.EXITED or not process.is_running:
                skipped += 1
                continue
            if process.terminate():
                terminated += 1
            else:
                skipped += 1

        if terminated:
            self.message_user(
                request,
                f"Killed {terminated} running process{'es' if terminated != 1 else ''}.",
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} process{'es' if skipped != 1 else ''} that were already exited.",
                level=messages.INFO,
            )

        return terminated, skipped

    @admin.action(description="Kill selected processes")
    def kill_processes(self, request, queryset):
        self._terminate_processes(request, queryset)

    @action(
        label="Kill",
        description="Kill this process if it is still running",
        attrs={"class": "deletelink"},
        methods=("POST",),
    )
    def kill_process(self, request, obj):
        self._terminate_processes(request, [obj])
        return redirect("admin:machine_process_change", obj.pk)

    @admin.display(description="Machine", ordering="machine__id")
    def machine_info(self, process):
        return format_html(
            '<a href="/admin/machine/machine/{}/change"><b><code>[{}]</code></b> &nbsp; {}</a>',
            process.machine.id,
            str(process.machine.id)[:8],
            process.machine.hostname,
        )

    @admin.display(description="Binary", ordering="binary__name")
    def binary_info(self, process):
        if not process.binary:
            return "-"
        return format_html(
            '<a href="/admin/machine/binary/{}/change"><code>{}</code> v{}</a>',
            process.binary.id,
            process.binary.name,
            process.binary.version,
        )

    @admin.display(description="Binary", ordering="binary__name")
    def binary_link(self, process):
        return self.binary_info(process)

    @admin.display(description="Network Interface", ordering="iface__id")
    def iface_link(self, process):
        if not process.iface:
            return "-"
        return format_html(
            '<a href="/admin/machine/networkinterface/{}/change"><code>{}</code> {}</a>',
            process.iface.id,
            str(process.iface.id)[:8],
            process.iface.iface or process.iface.ip_public or process.iface.ip_local,
        )

    @admin.display(description="ArchiveResult", ordering="archiveresult__plugin")
    def archiveresult_link(self, process):
        try:
            ar = process.archiveresult
        except Process.archiveresult.RelatedObjectDoesNotExist:
            return "-"
        return format_html(
            '<a href="/admin/core/archiveresult/{}/change">{} ← <code>{}</code></a>',
            ar.id,
            ar.snapshot.url[:50],
            ar.plugin,
        )

    @admin.display(description="Snapshot", ordering="archiveresult__snapshot__id")
    def snapshot_link(self, process):
        try:
            snapshot = process.archiveresult.snapshot
        except Process.archiveresult.RelatedObjectDoesNotExist:
            return "-"
        return format_html(
            '<a href="/admin/core/snapshot/{}/change"><code>{}</code></a>',
            snapshot.id,
            str(snapshot.id)[:8],
        )

    @admin.display(description="Crawl", ordering="archiveresult__snapshot__crawl__id")
    def crawl_link(self, process):
        try:
            crawl = process.archiveresult.snapshot.crawl
        except Process.archiveresult.RelatedObjectDoesNotExist:
            return "-"
        return format_html(
            '<a href="/admin/crawls/crawl/{}/change"><code>{}</code></a>',
            crawl.id,
            str(crawl.id)[:8],
        )

    @admin.display(description="Command", ordering="cmd")
    def cmd_str(self, process):
        if not process.cmd:
            return "-"
        # Compact the list-view rendering only — the change-page ``cmd_display``
        # still shows the full original ``process.cmd`` (and the DB row is
        # untouched). If the first argv token looks like an absolute path,
        # collapse it to its basename so a row like
        # ``/Users/.../.venv/bin/python -m archivebox foo`` reads as
        # ``python -m archivebox foo`` in the column.
        if isinstance(process.cmd, list):
            parts = [str(arg) for arg in process.cmd[:3]]
            if parts and (parts[0].startswith("/") or parts[0].startswith("~")):
                parts[0] = Path(parts[0]).name
            cmd = " ".join(parts)
            if len(process.cmd) > 3:
                cmd += " ..."
        else:
            cmd = str(process.cmd)
        return format_html('<code style="font-size: 0.9em;">{}</code>', cmd[:80])

    @admin.display(description="Status", ordering="status")
    def status_badge(self, process):
        # Pill-style badge matching the look of other admin status columns.
        # Color rules requested by the operator:
        #   RUNNING            → green
        #   EXITED, code == 0  → grey (clean exit)
        #   EXITED, code == 10 → grey (treated as a clean / "skipped" exit)
        #   EXITED, code other → red (failure)
        #   QUEUED / anything  → amber so it stands out without screaming
        status_value = str(process.status or "").lower()
        label = (process.get_status_display() or status_value or "?").upper()
        exit_code = process.exit_code
        if status_value == Process.StatusChoices.RUNNING:
            bg, fg = "#16a34a", "#fff"
        elif status_value == Process.StatusChoices.EXITED:
            if exit_code in (0, 10):
                bg, fg = "#6b7280", "#fff"
            else:
                bg, fg = "#dc2626", "#fff"
        else:
            bg, fg = "#f59e0b", "#fff"
        return format_html(
            '<span style="display:inline-block;background:{};color:{};'
            "padding:1px 6px;border-radius:3px;font-weight:800;font-size:11px;"
            'letter-spacing:0.3px;text-transform:uppercase;">{}</span>',
            bg,
            fg,
            label,
        )

    @admin.display(description="Duration", ordering="runtime_sort")
    def duration_display(self, process):
        return _format_process_duration_seconds(process.started_at, process.ended_at)

    @admin.display(description="Output", ordering="archiveresult__output_size")
    def output_summary(self, process):
        try:
            output_files = process.archiveresult.output_files or {}
        except Process.archiveresult.RelatedObjectDoesNotExist:
            output_files = {}

        if isinstance(output_files, str):
            try:
                output_files = json.loads(output_files)
            except (json.JSONDecodeError, TypeError, ValueError):
                output_files = {}

        file_count = 0
        total_bytes = 0

        if isinstance(output_files, dict):
            file_count = len(output_files)
            items = output_files.values()
        elif isinstance(output_files, (list, tuple, set)):
            file_count = len(output_files)
            items = output_files
        else:
            items = ()

        for metadata in items:
            if not isinstance(metadata, dict):
                continue
            size = metadata.get("size", 0)
            try:
                total_bytes += int(size or 0)
            except (TypeError, ValueError):
                continue

        file_label = "file" if file_count == 1 else "files"
        return format_html(
            '<code style="font-size: 0.9em;">{} {} • {}</code>',
            file_count,
            file_label,
            printable_filesize(total_bytes),
        )

    @admin.display(description="Command")
    def cmd_display(self, process):
        if not process.cmd:
            return "-"
        if isinstance(process.cmd, list):
            cmd = shlex.join(str(arg) for arg in process.cmd)
        else:
            cmd = str(process.cmd)
        return _render_copy_block(cmd)

    @admin.display(description="Environment")
    def env_display(self, process):
        env_text = env_to_dotenv_text(process.env)
        if not env_text:
            return "-"
        return _render_copy_block(env_text, multiline=True)

    @admin.display(description="Stdout")
    def stdout_display(self, process):
        if not process.stdout:
            return "-"
        return _render_copy_block(process.stdout, multiline=True)

    @admin.display(description="Stderr")
    def stderr_display(self, process):
        if not process.stderr:
            return "-"
        return _render_copy_block(process.stderr, multiline=True)

    @admin.display(description="ArchiveResult Output")
    def archiveresult_output_display(self, process):
        try:
            output = process.archiveresult.output_str
        except Process.archiveresult.RelatedObjectDoesNotExist:
            return "-"
        if not output:
            return "-"
        return _render_copy_block(output, multiline=True)


def register_admin(admin_site):
    admin_site.register(Machine, MachineAdmin)
    admin_site.register(NetworkInterface, NetworkInterfaceAdmin)
    admin_site.register(Binary, BinaryAdmin)
    admin_site.register(Process, ProcessAdmin)
