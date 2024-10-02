__package__ = 'archivebox.machine'

import socket

from django.db import models
from archivebox.abid_utils.models import ABIDModel, ABIDField, AutoDateTimeField

from .detect import get_host_guid, get_os_info, get_vm_info, get_host_network, get_host_stats

CURRENT_MACHINE = None
CURRENT_INTERFACE = None

class MachineManager(models.Manager):
    def current(self) -> 'Machine':
        global CURRENT_MACHINE
        if CURRENT_MACHINE:
            return CURRENT_MACHINE
        
        guid = get_host_guid()
        try:
            CURRENT_MACHINE = self.get(guid=guid)
            return CURRENT_MACHINE
        except self.model.DoesNotExist:
            pass
        
        CURRENT_MACHINE = self.model(
            guid=guid,
            hostname=socket.gethostname(),
            **get_os_info(),
            **get_vm_info(),
            stats=get_host_stats(),
        )
        CURRENT_MACHINE.save()
        return CURRENT_MACHINE

class Machine(ABIDModel):
    abid_prefix = 'mxn_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.guid'
    abid_subtype_src = '"01"'
    abid_rand_src = 'self.id'
    abid_drift_allowed = False

    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)

    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    # IMMUTABLE PROPERTIES
    guid = models.CharField(max_length=64, default=None, null=False, unique=True, editable=False)
    
    # MUTABLE PROPERTIES
    hostname = models.CharField(max_length=63, default=None, null=False)
    
    hw_in_docker = models.BooleanField(default=False, null=False)
    hw_in_vm = models.BooleanField(default=False, null=False)
    hw_manufacturer = models.CharField(max_length=63, default=None, null=False) # e.g. Apple
    hw_product = models.CharField(max_length=63, default=None, null=False)      # e.g. Mac Studio Mac13,1
    hw_uuid = models.CharField(max_length=255, default=None, null=False)        # e.g. 39A12B50-...-...-...-...
    
    os_arch = models.CharField(max_length=15, default=None, null=False)         # e.g. arm64
    os_family = models.CharField(max_length=15, default=None, null=False)       # e.g. darwin
    os_platform = models.CharField(max_length=63, default=None, null=False)     # e.g. macOS-14.6.1-arm64-arm-64bit
    os_release = models.CharField(max_length=63, default=None, null=False)      # e.g. macOS 14.6.1
    os_kernel = models.CharField(max_length=255, default=None, null=False)      # e.g. Darwin Kernel Version 23.6.0: Mon Jul 29 21:14:30 PDT 2024; root:xnu-10063.141.2~1/RELEASE_ARM64_T6000
    
    stats = models.JSONField(default=None, null=False)
    
    objects = MachineManager()
    
    networkinterface_set: models.Manager['NetworkInterface']


class NetworkInterfaceManager(models.Manager):
    def current(self) -> 'NetworkInterface':
        global CURRENT_INTERFACE
        if CURRENT_INTERFACE:
            return CURRENT_INTERFACE
        
        machine = Machine.objects.current()
        net_info = get_host_network()
        try:
            CURRENT_INTERFACE = self.get(
                machine=machine,
                ip_public=net_info['ip_public'],
                ip_local=net_info['ip_local'],
                mac_address=net_info['mac_address'],
                dns_server=net_info['dns_server'],
            )
            return CURRENT_INTERFACE
        except self.model.DoesNotExist:
            pass
        
        CURRENT_INTERFACE = self.model(
            machine=machine,
            **get_host_network(),
        )
        CURRENT_INTERFACE.save()
        return CURRENT_INTERFACE
            


class NetworkInterface(ABIDModel):
    abid_prefix = 'ixf_'
    abid_ts_src = 'self.machine.created_at'
    abid_uri_src = 'self.machine.guid'
    abid_subtype_src = 'self.iface'
    abid_rand_src = 'self.id'
    abid_drift_allowed = False
    
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)

    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, default=None, null=False)

    # IMMUTABLE PROPERTIES
    mac_address = models.CharField(max_length=17, default=None, null=False, editable=False)   # e.g. ab:cd:ef:12:34:56
    ip_public = models.GenericIPAddressField(default=None, null=False, editable=False)        # e.g. 123.123.123.123 or 2001:0db8:85a3:0000:0000:8a2e:0370:7334
    ip_local = models.GenericIPAddressField(default=None, null=False, editable=False)         # e.g. 192.168.2.18    or 2001:0db8:85a3:0000:0000:8a2e:0370:7334
    dns_server = models.GenericIPAddressField(default=None, null=False, editable=False)       # e.g. 8.8.8.8         or 2001:0db8:85a3:0000:0000:8a2e:0370:7334
    
    # MUTABLE PROPERTIES
    iface = models.CharField(max_length=15, default=None, null=False)                         # e.g. en0
    hostname = models.CharField(max_length=63, default=None, null=False)                      # e.g. somehost.sub.example.com
    isp = models.CharField(max_length=63, default=None, null=False)                           # e.g. AS-SONICTELECOM
    city = models.CharField(max_length=63, default=None, null=False)                          # e.g. Berkeley
    region = models.CharField(max_length=63, default=None, null=False)                        # e.g. California
    country = models.CharField(max_length=63, default=None, null=False)                       # e.g. United States

    objects = NetworkInterfaceManager()
    
    class Meta:
        unique_together = (
            ('machine', 'ip_public', 'ip_local', 'mac_address', 'dns_server'),
        )
        

# class InstalledBinary(ABIDModel):
#     abid_prefix = 'bin_'
#     abid_ts_src = 'self.machine.created_at'
#     abid_uri_src = 'self.machine.guid'
#     abid_subtype_src = 'self.binprovider'
#     abid_rand_src = 'self.id'
#     abid_drift_allowed = False
    
#     id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
#     abid = ABIDField(prefix=abid_prefix)

#     created_at = AutoDateTimeField(default=None, null=False, db_index=True)
#     modified_at = models.DateTimeField(auto_now=True)
    
#     machine = models.ForeignKey(Machine, on_delete=models.CASCADE, default=None, null=False)
#     binprovider = models.CharField(max_length=255, default=None, null=False)
    
#     name = models.CharField(max_length=255, default=None, null=False)
#     version = models.CharField(max_length=255, default=None, null=False)
#     abspath = models.CharField(max_length=255, default=None, null=False)
#     sha256 = models.CharField(max_length=255, default=None, null=False)
    
#     class Meta:
#         unique_together = (
#             ('machine', 'binprovider', 'version', 'abspath', 'sha256'),
#         )
