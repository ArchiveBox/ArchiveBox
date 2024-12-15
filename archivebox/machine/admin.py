__package__ = 'archivebox.machine'

import abx

from django.contrib import admin
from django.utils.html import format_html

from archivebox.base_models.admin import ABIDModelAdmin

from machine.models import Machine, NetworkInterface, InstalledBinary



class MachineAdmin(ABIDModelAdmin):
    list_display = ('abid', 'created_at', 'hostname', 'ips', 'os_platform', 'hw_in_docker', 'hw_in_vm', 'hw_manufacturer', 'hw_product', 'os_arch', 'os_family', 'os_release', 'hw_uuid', 'health')
    sort_fields = ('abid', 'created_at', 'hostname', 'ips', 'os_platform', 'hw_in_docker', 'hw_in_vm', 'hw_manufacturer', 'hw_product', 'os_arch', 'os_family', 'os_release', 'hw_uuid')
    # search_fields = ('id', 'abid', 'guid', 'hostname', 'hw_manufacturer', 'hw_product', 'hw_uuid', 'os_arch', 'os_family', 'os_platform', 'os_kernel', 'os_release')
    
    readonly_fields = ('guid', 'created_at', 'modified_at', 'abid_info', 'ips')
    fields = (*readonly_fields, 'hostname', 'hw_in_docker', 'hw_in_vm', 'hw_manufacturer', 'hw_product', 'hw_uuid', 'os_arch', 'os_family', 'os_platform', 'os_kernel', 'os_release', 'stats', 'num_uses_succeeded', 'num_uses_failed')

    list_filter = ('hw_in_docker', 'hw_in_vm', 'os_arch', 'os_family', 'os_platform')
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]

    @admin.display(
        description='Public IP',
        ordering='networkinterface__ip_public',
    )
    def ips(self, machine):
        return format_html(
            '<a href="/admin/machine/networkinterface/?q={}"><b><code>{}</code></b></a>',
            machine.abid,
            ', '.join(machine.networkinterface_set.values_list('ip_public', flat=True)),
        )

class NetworkInterfaceAdmin(ABIDModelAdmin):
    list_display = ('abid', 'created_at', 'machine_info', 'ip_public', 'dns_server', 'isp', 'country', 'region', 'city', 'iface', 'ip_local', 'mac_address', 'health')
    sort_fields = ('abid', 'created_at', 'machine_info', 'ip_public', 'dns_server', 'isp', 'country', 'region', 'city', 'iface', 'ip_local', 'mac_address')
    search_fields = ('abid', 'machine__abid', 'iface', 'ip_public', 'ip_local', 'mac_address', 'dns_server', 'hostname', 'isp', 'city', 'region', 'country')
    
    readonly_fields = ('machine', 'created_at', 'modified_at', 'abid_info', 'mac_address', 'ip_public', 'ip_local', 'dns_server')
    fields = (*readonly_fields, 'iface', 'hostname', 'isp', 'city', 'region', 'country', 'num_uses_succeeded', 'num_uses_failed')

    list_filter = ('isp', 'country', 'region')
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]

    @admin.display(
        description='Machine',
        ordering='machine__abid',
    )
    def machine_info(self, iface):
        return format_html(
            '<a href="/admin/machine/machine/{}/change"><b><code>[{}]</code></b> &nbsp; {}</a>',
            iface.machine.id,
            iface.machine.abid,
            iface.machine.hostname,
        )

class InstalledBinaryAdmin(ABIDModelAdmin):
    list_display = ('abid', 'created_at', 'machine_info', 'name', 'binprovider', 'version', 'abspath', 'sha256', 'health')
    sort_fields = ('abid', 'created_at', 'machine_info', 'name', 'binprovider', 'version', 'abspath', 'sha256')
    search_fields = ('abid', 'machine__abid', 'name', 'binprovider', 'version', 'abspath', 'sha256')
    
    readonly_fields = ('created_at', 'modified_at', 'abid_info')
    fields = ('machine', 'name', 'binprovider', 'abspath', 'version', 'sha256', *readonly_fields, 'num_uses_succeeded', 'num_uses_failed')

    list_filter = ('name', 'binprovider', 'machine_id')
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]

    @admin.display(
        description='Machine',
        ordering='machine__abid',
    )
    def machine_info(self, installed_binary):
        return format_html(
            '<a href="/admin/machine/machine/{}/change"><b><code>[{}]</code></b> &nbsp; {}</a>',
            installed_binary.machine.id,
            installed_binary.machine.abid,
            installed_binary.machine.hostname,
        )



@abx.hookimpl
def register_admin(admin_site):
    admin_site.register(Machine, MachineAdmin)
    admin_site.register(NetworkInterface, NetworkInterfaceAdmin)
    admin_site.register(InstalledBinary, InstalledBinaryAdmin)
