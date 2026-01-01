__package__ = 'archivebox.machine'

from django.contrib import admin
from django.utils.html import format_html

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin
from archivebox.machine.models import Machine, NetworkInterface, Binary, Process


class MachineAdmin(ConfigEditorMixin, BaseModelAdmin):
    list_display = ('id', 'created_at', 'hostname', 'ips', 'os_platform', 'hw_in_docker', 'hw_in_vm', 'hw_manufacturer', 'hw_product', 'os_arch', 'os_family', 'os_release', 'hw_uuid', 'health_display')
    sort_fields = ('id', 'created_at', 'hostname', 'ips', 'os_platform', 'hw_in_docker', 'hw_in_vm', 'hw_manufacturer', 'hw_product', 'os_arch', 'os_family', 'os_release', 'hw_uuid')

    readonly_fields = ('guid', 'created_at', 'modified_at', 'ips')

    fieldsets = (
        ('Identity', {
            'fields': ('hostname', 'guid', 'ips'),
            'classes': ('card',),
        }),
        ('Hardware', {
            'fields': ('hw_manufacturer', 'hw_product', 'hw_uuid', 'hw_in_docker', 'hw_in_vm'),
            'classes': ('card',),
        }),
        ('Operating System', {
            'fields': ('os_platform', 'os_family', 'os_arch', 'os_kernel', 'os_release'),
            'classes': ('card',),
        }),
        ('Statistics', {
            'fields': ('stats', 'num_uses_succeeded', 'num_uses_failed'),
            'classes': ('card',),
        }),
        ('Configuration', {
            'fields': ('config',),
            'classes': ('card', 'wide'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'modified_at'),
            'classes': ('card',),
        }),
    )

    list_filter = ('hw_in_docker', 'hw_in_vm', 'os_arch', 'os_family', 'os_platform')
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]

    @admin.display(description='Public IP', ordering='networkinterface__ip_public')
    def ips(self, machine):
        return format_html(
            '<a href="/admin/machine/networkinterface/?q={}"><b><code>{}</code></b></a>',
            machine.id, ', '.join(machine.networkinterface_set.values_list('ip_public', flat=True)),
        )

    @admin.display(description='Health', ordering='health')
    def health_display(self, obj):
        h = obj.health
        color = 'green' if h >= 80 else 'orange' if h >= 50 else 'red'
        return format_html('<span style="color: {};">{}</span>', color, h)


class NetworkInterfaceAdmin(BaseModelAdmin):
    list_display = ('id', 'created_at', 'machine_info', 'ip_public', 'dns_server', 'isp', 'country', 'region', 'city', 'iface', 'ip_local', 'mac_address', 'health_display')
    sort_fields = ('id', 'created_at', 'machine_info', 'ip_public', 'dns_server', 'isp', 'country', 'region', 'city', 'iface', 'ip_local', 'mac_address')
    search_fields = ('id', 'machine__id', 'iface', 'ip_public', 'ip_local', 'mac_address', 'dns_server', 'hostname', 'isp', 'city', 'region', 'country')

    readonly_fields = ('machine', 'created_at', 'modified_at', 'mac_address', 'ip_public', 'ip_local', 'dns_server')

    fieldsets = (
        ('Machine', {
            'fields': ('machine',),
            'classes': ('card',),
        }),
        ('Network', {
            'fields': ('iface', 'ip_public', 'ip_local', 'mac_address', 'dns_server'),
            'classes': ('card',),
        }),
        ('Location', {
            'fields': ('hostname', 'isp', 'city', 'region', 'country'),
            'classes': ('card',),
        }),
        ('Usage', {
            'fields': ('num_uses_succeeded', 'num_uses_failed'),
            'classes': ('card',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'modified_at'),
            'classes': ('card',),
        }),
    )

    list_filter = ('isp', 'country', 'region')
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]

    @admin.display(description='Machine', ordering='machine__id')
    def machine_info(self, iface):
        return format_html(
            '<a href="/admin/machine/machine/{}/change"><b><code>[{}]</code></b> &nbsp; {}</a>',
            iface.machine.id, str(iface.machine.id)[:8], iface.machine.hostname,
        )

    @admin.display(description='Health', ordering='health')
    def health_display(self, obj):
        h = obj.health
        color = 'green' if h >= 80 else 'orange' if h >= 50 else 'red'
        return format_html('<span style="color: {};">{}</span>', color, h)


class BinaryAdmin(BaseModelAdmin):
    list_display = ('id', 'created_at', 'machine_info', 'name', 'binprovider', 'version', 'abspath', 'sha256', 'status', 'health_display')
    sort_fields = ('id', 'created_at', 'machine_info', 'name', 'binprovider', 'version', 'abspath', 'sha256', 'status')
    search_fields = ('id', 'machine__id', 'name', 'binprovider', 'version', 'abspath', 'sha256')

    readonly_fields = ('created_at', 'modified_at')

    fieldsets = (
        ('Binary Info', {
            'fields': ('name', 'binproviders', 'binprovider', 'overrides'),
            'classes': ('card',),
        }),
        ('Location', {
            'fields': ('machine', 'abspath'),
            'classes': ('card',),
        }),
        ('Version', {
            'fields': ('version', 'sha256'),
            'classes': ('card',),
        }),
        ('State', {
            'fields': ('status', 'retry_at', 'output_dir'),
            'classes': ('card',),
        }),
        ('Usage', {
            'fields': ('num_uses_succeeded', 'num_uses_failed'),
            'classes': ('card',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'modified_at'),
            'classes': ('card',),
        }),
    )

    list_filter = ('name', 'binprovider', 'status', 'machine_id')
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]

    @admin.display(description='Machine', ordering='machine__id')
    def machine_info(self, binary):
        return format_html(
            '<a href="/admin/machine/machine/{}/change"><b><code>[{}]</code></b> &nbsp; {}</a>',
            binary.machine.id, str(binary.machine.id)[:8], binary.machine.hostname,
        )

    @admin.display(description='Health', ordering='health')
    def health_display(self, obj):
        h = obj.health
        color = 'green' if h >= 80 else 'orange' if h >= 50 else 'red'
        return format_html('<span style="color: {};">{}</span>', color, h)


class ProcessAdmin(BaseModelAdmin):
    list_display = ('id', 'created_at', 'machine_info', 'archiveresult_link', 'cmd_str', 'status', 'exit_code', 'pid', 'binary_info')
    sort_fields = ('id', 'created_at', 'status', 'exit_code', 'pid')
    search_fields = ('id', 'machine__id', 'binary__name', 'cmd', 'pwd', 'stdout', 'stderr')

    readonly_fields = ('created_at', 'modified_at', 'machine', 'binary', 'iface', 'archiveresult_link')

    fieldsets = (
        ('Process Info', {
            'fields': ('machine', 'archiveresult_link', 'status', 'retry_at'),
            'classes': ('card',),
        }),
        ('Command', {
            'fields': ('cmd', 'pwd', 'env', 'timeout'),
            'classes': ('card', 'wide'),
        }),
        ('Execution', {
            'fields': ('binary', 'iface', 'pid', 'exit_code', 'url'),
            'classes': ('card',),
        }),
        ('Timing', {
            'fields': ('started_at', 'ended_at'),
            'classes': ('card',),
        }),
        ('Output', {
            'fields': ('stdout', 'stderr'),
            'classes': ('card', 'wide', 'collapse'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'modified_at'),
            'classes': ('card',),
        }),
    )

    list_filter = ('status', 'exit_code', 'machine_id')
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]

    @admin.display(description='Machine', ordering='machine__id')
    def machine_info(self, process):
        return format_html(
            '<a href="/admin/machine/machine/{}/change"><b><code>[{}]</code></b> &nbsp; {}</a>',
            process.machine.id, str(process.machine.id)[:8], process.machine.hostname,
        )

    @admin.display(description='Binary', ordering='binary__name')
    def binary_info(self, process):
        if not process.binary:
            return '-'
        return format_html(
            '<a href="/admin/machine/binary/{}/change"><code>{}</code> v{}</a>',
            process.binary.id, process.binary.name, process.binary.version,
        )

    @admin.display(description='ArchiveResult')
    def archiveresult_link(self, process):
        if not hasattr(process, 'archiveresult'):
            return '-'
        ar = process.archiveresult
        return format_html(
            '<a href="/admin/core/archiveresult/{}/change"><code>{}</code> → {}</a>',
            ar.id, ar.plugin, ar.snapshot.url[:50],
        )

    @admin.display(description='Command')
    def cmd_str(self, process):
        if not process.cmd:
            return '-'
        cmd = ' '.join(process.cmd[:3]) if isinstance(process.cmd, list) else str(process.cmd)
        if len(process.cmd) > 3:
            cmd += ' ...'
        return format_html('<code style="font-size: 0.9em;">{}</code>', cmd[:80])


def register_admin(admin_site):
    admin_site.register(Machine, MachineAdmin)
    admin_site.register(NetworkInterface, NetworkInterfaceAdmin)
    admin_site.register(Binary, BinaryAdmin)
    admin_site.register(Process, ProcessAdmin)
