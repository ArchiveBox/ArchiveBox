__package__ = 'archivebox.machine'

from django.contrib import admin
from django.utils.html import format_html

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin
from archivebox.machine.models import Machine, NetworkInterface, Binary


class MachineAdmin(ConfigEditorMixin, BaseModelAdmin):
    list_display = ('id', 'created_at', 'hostname', 'ips', 'os_platform', 'hw_in_docker', 'hw_in_vm', 'hw_manufacturer', 'hw_product', 'os_arch', 'os_family', 'os_release', 'hw_uuid', 'health')
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


class NetworkInterfaceAdmin(BaseModelAdmin):
    list_display = ('id', 'created_at', 'machine_info', 'ip_public', 'dns_server', 'isp', 'country', 'region', 'city', 'iface', 'ip_local', 'mac_address', 'health')
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


class BinaryAdmin(BaseModelAdmin):
    list_display = ('id', 'created_at', 'machine_info', 'name', 'binprovider', 'version', 'abspath', 'sha256', 'status', 'health')
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


def register_admin(admin_site):
    admin_site.register(Machine, MachineAdmin)
    admin_site.register(NetworkInterface, NetworkInterfaceAdmin)
    admin_site.register(Binary, BinaryAdmin)
