__package__ = "archivebox.machine"

import json
import shlex

from django.contrib import admin, messages
from django.db.models import DurationField, ExpressionWrapper, F
from django.db.models.functions import Coalesce, Now
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.html import format_html
from django_object_actions import action

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin
from archivebox.misc.logging_util import printable_filesize
from archivebox.machine.env_utils import env_to_dotenv_text
from archivebox.machine.models import Machine, NetworkInterface, Binary, Process


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
    list_display = (
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
            "Configuration",
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
    ordering = ["-created_at"]
    list_per_page = 100
    actions = ["delete_selected"]

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
    ordering = ["-created_at"]
    list_per_page = 100
    actions = ["delete_selected"]

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
    ordering = ["-created_at"]
    list_per_page = 100
    actions = ["delete_selected"]

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


class ProcessAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "created_at",
        "machine_info",
        "archiveresult_link",
        "snapshot_link",
        "crawl_link",
        "cmd_str",
        "status",
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
        "status",
        "duration_display",
        "exit_code",
        "pid",
        "output_summary",
        "binary_info",
    )
    search_fields = ("id", "machine__id", "binary__name", "cmd", "pwd", "stdout", "stderr")

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
                "fields": ("stdout", "stderr"),
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

    list_filter = ("status", "exit_code", "machine_id")
    ordering = ["-created_at"]
    list_per_page = 100
    actions = ["kill_processes", "delete_selected"]
    change_actions = ["kill_process"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "machine",
                "binary",
                "iface",
                "archiveresult__snapshot__crawl",
            )
            .annotate(
                runtime_sort=ExpressionWrapper(
                    Coalesce(F("ended_at"), Now()) - F("started_at"),
                    output_field=DurationField(),
                ),
            )
        )

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
        if not hasattr(process, "archiveresult"):
            return "-"
        ar = process.archiveresult
        return format_html(
            '<a href="/admin/core/archiveresult/{}/change">{} ← <code>{}</code></a>',
            ar.id,
            ar.snapshot.url[:50],
            ar.plugin,
        )

    @admin.display(description="Snapshot", ordering="archiveresult__snapshot__id")
    def snapshot_link(self, process):
        ar = getattr(process, "archiveresult", None)
        snapshot = getattr(ar, "snapshot", None)
        if not snapshot:
            return "-"
        return format_html(
            '<a href="/admin/core/snapshot/{}/change"><code>{}</code></a>',
            snapshot.id,
            str(snapshot.id)[:8],
        )

    @admin.display(description="Crawl", ordering="archiveresult__snapshot__crawl__id")
    def crawl_link(self, process):
        ar = getattr(process, "archiveresult", None)
        snapshot = getattr(ar, "snapshot", None)
        crawl = getattr(snapshot, "crawl", None)
        if not crawl:
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
        cmd = " ".join(process.cmd[:3]) if isinstance(process.cmd, list) else str(process.cmd)
        if len(process.cmd) > 3:
            cmd += " ..."
        return format_html('<code style="font-size: 0.9em;">{}</code>', cmd[:80])

    @admin.display(description="Duration", ordering="runtime_sort")
    def duration_display(self, process):
        return _format_process_duration_seconds(process.started_at, process.ended_at)

    @admin.display(description="Output", ordering="archiveresult__output_size")
    def output_summary(self, process):
        output_files = getattr(getattr(process, "archiveresult", None), "output_files", {}) or {}

        if isinstance(output_files, str):
            try:
                output_files = json.loads(output_files)
            except Exception:
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


def register_admin(admin_site):
    admin_site.register(Machine, MachineAdmin)
    admin_site.register(NetworkInterface, NetworkInterfaceAdmin)
    admin_site.register(Binary, BinaryAdmin)
    admin_site.register(Process, ProcessAdmin)
