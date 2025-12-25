__package__ = 'archivebox.machine'

from django.contrib import admin
from django.utils.html import format_html

from archivebox.base_models.admin import BaseModelAdmin, ConfigEditorMixin
from machine.models import Machine, NetworkInterface, InstalledBinary, Dependency


class MachineAdmin(ConfigEditorMixin, BaseModelAdmin):
    list_display = ('id', 'created_at', 'hostname', 'ips', 'os_platform', 'hw_in_docker', 'hw_in_vm', 'hw_manufacturer', 'hw_product', 'os_arch', 'os_family', 'os_release', 'hw_uuid', 'health')
    sort_fields = ('id', 'created_at', 'hostname', 'ips', 'os_platform', 'hw_in_docker', 'hw_in_vm', 'hw_manufacturer', 'hw_product', 'os_arch', 'os_family', 'os_release', 'hw_uuid')

    readonly_fields = ('guid', 'created_at', 'modified_at', 'ips')
    fields = (*readonly_fields, 'hostname', 'hw_in_docker', 'hw_in_vm', 'hw_manufacturer', 'hw_product', 'hw_uuid', 'os_arch', 'os_family', 'os_platform', 'os_kernel', 'os_release', 'stats', 'config', 'num_uses_succeeded', 'num_uses_failed')

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
    fields = (*readonly_fields, 'iface', 'hostname', 'isp', 'city', 'region', 'country', 'num_uses_succeeded', 'num_uses_failed')

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


class DependencyAdmin(ConfigEditorMixin, BaseModelAdmin):
    list_display = ('id', 'created_at', 'bin_name', 'bin_providers', 'is_installed', 'installed_count')
    sort_fields = ('id', 'created_at', 'bin_name', 'bin_providers')
    search_fields = ('id', 'bin_name', 'bin_providers')

    readonly_fields = ('id', 'created_at', 'modified_at', 'is_installed', 'installed_count')
    fields = ('bin_name', 'bin_providers', 'custom_cmds', 'config', *readonly_fields)

    list_filter = ('bin_providers', 'created_at')
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]

    @admin.display(description='Installed', boolean=True)
    def is_installed(self, dependency):
        return dependency.is_installed

    @admin.display(description='# Binaries')
    def installed_count(self, dependency):
        count = dependency.installed_binaries.count()
        if count:
            return format_html(
                '<a href="/admin/machine/installedbinary/?dependency__id__exact={}">{}</a>',
                dependency.id, count,
            )
        return '0'


class InstalledBinaryAdmin(BaseModelAdmin):
    list_display = ('id', 'created_at', 'machine_info', 'name', 'dependency_link', 'binprovider', 'version', 'abspath', 'sha256', 'health')
    sort_fields = ('id', 'created_at', 'machine_info', 'name', 'binprovider', 'version', 'abspath', 'sha256')
    search_fields = ('id', 'machine__id', 'name', 'binprovider', 'version', 'abspath', 'sha256', 'dependency__bin_name')

    readonly_fields = ('created_at', 'modified_at')
    fields = ('machine', 'dependency', 'name', 'binprovider', 'abspath', 'version', 'sha256', *readonly_fields, 'num_uses_succeeded', 'num_uses_failed')

    list_filter = ('name', 'binprovider', 'machine_id', 'dependency')
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]

    @admin.display(description='Machine', ordering='machine__id')
    def machine_info(self, installed_binary):
        return format_html(
            '<a href="/admin/machine/machine/{}/change"><b><code>[{}]</code></b> &nbsp; {}</a>',
            installed_binary.machine.id, str(installed_binary.machine.id)[:8], installed_binary.machine.hostname,
        )

    @admin.display(description='Dependency', ordering='dependency__bin_name')
    def dependency_link(self, installed_binary):
        if installed_binary.dependency:
            return format_html(
                '<a href="/admin/machine/dependency/{}/change">{}</a>',
                installed_binary.dependency.id, installed_binary.dependency.bin_name,
            )
        return '-'


def register_admin(admin_site):
    admin_site.register(Machine, MachineAdmin)
    admin_site.register(NetworkInterface, NetworkInterfaceAdmin)
    admin_site.register(Dependency, DependencyAdmin)
    admin_site.register(InstalledBinary, InstalledBinaryAdmin)
