__package__ = 'archivebox.machine'

import socket
from datetime import timedelta
from pathlib import Path

from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property


import abx.archivebox.use
from abx.archivebox.base_binary import BaseBinary, BaseBinProvider
from archivebox.abid_utils.models import ABIDModel, ABIDField, AutoDateTimeField

from .detect import get_host_guid, get_os_info, get_vm_info, get_host_network, get_host_stats

CURRENT_MACHINE = None                              # global cache for the current machine
CURRENT_INTERFACE = None                            # global cache for the current network interface
CURRENT_BINARIES = {}                               # global cache for the currently installed binaries
MACHINE_RECHECK_INTERVAL = 7 * 24 * 60 * 60         # 1 week (how often should we check for OS/hardware changes?)
NETWORK_INTERFACE_RECHECK_INTERVAL = 1 * 60 * 60    # 1 hour (how often should we check for public IP/private IP/DNS changes?)
INSTALLED_BINARY_RECHECK_INTERVAL = 1 * 30 * 60     # 30min  (how often should we check for changes to locally installed binaries?)


class ModelWithHealthStats(models.Model):
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)
    
    class Meta:
        abstract = True
    
    def record_health_failure(self) -> None:
        self.num_uses_failed += 1
        self.save()

    def record_health_success(self) -> None:
        self.num_uses_succeeded += 1
        self.save()
        
    def reset_health(self) -> None:
        # move all the failures to successes when resetting so we dont lose track of the total count
        self.num_uses_succeeded = self.num_uses_failed + self.num_uses_succeeded
        self.num_uses_failed = 0
        self.save()
        
    @property
    def health(self) -> int:
        total_uses = max((self.num_uses_failed + self.num_uses_succeeded, 1))
        success_pct = (self.num_uses_succeeded / total_uses) * 100
        return round(success_pct)


class MachineManager(models.Manager):
    def current(self) -> 'Machine':
        """Get the current machine that ArchiveBox is running on."""
        
        global CURRENT_MACHINE
        if CURRENT_MACHINE:
            expires_at = CURRENT_MACHINE.modified_at + timedelta(seconds=MACHINE_RECHECK_INTERVAL)
            if timezone.now() < expires_at:
                # assume current machine cant change *while archivebox is actively running on it*
                # it's not strictly impossible to swap hardware while code is running,
                # but its rare and unusual so we check only once per week
                # (e.g. VMWare can live-migrate a VM to a new host while it's running)
                return CURRENT_MACHINE
            else:
                CURRENT_MACHINE = None
        
        CURRENT_MACHINE, _created = self.update_or_create(
            guid=get_host_guid(),
            defaults={
                'hostname': socket.gethostname(),
                **get_os_info(),
                **get_vm_info(),
                'stats': get_host_stats(),
            },
        )        
        CURRENT_MACHINE.save()  # populate ABID
        
        return CURRENT_MACHINE

class Machine(ABIDModel, ModelWithHealthStats):
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
    guid = models.CharField(max_length=64, default=None, null=False, unique=True, editable=False)  # 64char sha256 hash of machine's unique hardware ID
    
    # MUTABLE PROPERTIES
    hostname = models.CharField(max_length=63, default=None, null=False)        # e.g. somehost.subdomain.example.com
    hw_in_docker = models.BooleanField(default=False, null=False)               # e.g. False
    hw_in_vm = models.BooleanField(default=False, null=False)                   # e.g. False
    hw_manufacturer = models.CharField(max_length=63, default=None, null=False) # e.g. Apple
    hw_product = models.CharField(max_length=63, default=None, null=False)      # e.g. Mac Studio Mac13,1
    hw_uuid = models.CharField(max_length=255, default=None, null=False)        # e.g. 39A12B50-...-...-...-...
    
    os_arch = models.CharField(max_length=15, default=None, null=False)         # e.g. arm64
    os_family = models.CharField(max_length=15, default=None, null=False)       # e.g. darwin
    os_platform = models.CharField(max_length=63, default=None, null=False)     # e.g. macOS-14.6.1-arm64-arm-64bit
    os_release = models.CharField(max_length=63, default=None, null=False)      # e.g. macOS 14.6.1
    os_kernel = models.CharField(max_length=255, default=None, null=False)      # e.g. Darwin Kernel Version 23.6.0: Mon Jul 29 21:14:30 PDT 2024; root:xnu-10063.141.2~1/RELEASE_ARM64_T6000
    
    # STATS COUNTERS
    stats = models.JSONField(default=dict, null=False)                    # e.g. {"cpu_load": [1.25, 2.4, 1.4], "mem_swap_used_pct": 56, ...}
    # num_uses_failed = models.PositiveIntegerField(default=0)                  # from ModelWithHealthStats
    # num_uses_succeeded = models.PositiveIntegerField(default=0)
    
    objects: MachineManager = MachineManager()
    
    networkinterface_set: models.Manager['NetworkInterface']

    


class NetworkInterfaceManager(models.Manager):
    def current(self) -> 'NetworkInterface':
        """Get the current network interface for the current machine."""
        
        global CURRENT_INTERFACE
        if CURRENT_INTERFACE:
            # assume the current network interface (public IP, DNS servers, etc.) wont change more than once per hour
            expires_at = CURRENT_INTERFACE.modified_at + timedelta(seconds=NETWORK_INTERFACE_RECHECK_INTERVAL)
            if timezone.now() < expires_at:
                return CURRENT_INTERFACE
            else:
                CURRENT_INTERFACE = None
        
        machine = Machine.objects.current()
        net_info = get_host_network()
        CURRENT_INTERFACE, _created = self.update_or_create(
            machine=machine,
            ip_public=net_info.pop('ip_public'),
            ip_local=net_info.pop('ip_local'),
            mac_address=net_info.pop('mac_address'),
            dns_server=net_info.pop('dns_server'),
            defaults=net_info,
        )
        CURRENT_INTERFACE.save()  # populate ABID

        return CURRENT_INTERFACE
    



class NetworkInterface(ABIDModel, ModelWithHealthStats):
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
    
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, default=None, null=False)  # e.g. Machine(id=...)

    # IMMUTABLE PROPERTIES
    mac_address = models.CharField(max_length=17, default=None, null=False, editable=False)   # e.g. ab:cd:ef:12:34:56
    ip_public = models.GenericIPAddressField(default=None, null=False, editable=False)        # e.g. 123.123.123.123 or 2001:0db8:85a3:0000:0000:8a2e:0370:7334
    ip_local = models.GenericIPAddressField(default=None, null=False, editable=False)         # e.g. 192.168.2.18    or 2001:0db8:85a3:0000:0000:8a2e:0370:7334
    dns_server = models.GenericIPAddressField(default=None, null=False, editable=False)       # e.g. 8.8.8.8         or 2001:0db8:85a3:0000:0000:8a2e:0370:7334
    
    # MUTABLE PROPERTIES
    hostname = models.CharField(max_length=63, default=None, null=False)                      # e.g. somehost.sub.example.com
    iface = models.CharField(max_length=15, default=None, null=False)                         # e.g. en0
    isp = models.CharField(max_length=63, default=None, null=False)                           # e.g. AS-SONICTELECOM
    city = models.CharField(max_length=63, default=None, null=False)                          # e.g. Berkeley
    region = models.CharField(max_length=63, default=None, null=False)                        # e.g. California
    country = models.CharField(max_length=63, default=None, null=False)                       # e.g. United States

    # STATS COUNTERS (from ModelWithHealthStats)
    # num_uses_failed = models.PositiveIntegerField(default=0)
    # num_uses_succeeded = models.PositiveIntegerField(default=0)

    objects: NetworkInterfaceManager = NetworkInterfaceManager()
    
    class Meta:
        unique_together = (
            # if *any* of these change, it's considered a different interface
            # because we might get different downloaded content as a result,
            # this forces us to store an audit trail whenever these things change
            ('machine', 'ip_public', 'ip_local', 'mac_address', 'dns_server'),
        )


class InstalledBinaryManager(models.Manager):
    def get_from_db_or_cache(self, binary: BaseBinary) -> 'InstalledBinary':
        """Get or create an InstalledBinary record for a Binary on the local machine"""
        
        global CURRENT_BINARIES
        cached_binary = CURRENT_BINARIES.get(binary.id)
        if cached_binary:
            expires_at = cached_binary.modified_at + timedelta(seconds=INSTALLED_BINARY_RECHECK_INTERVAL)
            if timezone.now() < expires_at:
                is_loaded = binary.abspath and binary.version and binary.sha256
                if is_loaded:
                    # if the caller took did the (expensive) job of loading the binary from the filesystem already
                    # then their in-memory version is certainly more up-to-date than any potential cached version
                    # use this opportunity to invalidate the cache in case if anything has changed
                    is_different_from_cache = (
                        binary.abspath != cached_binary.abspath
                        or binary.version != cached_binary.version
                        or binary.sha256 != cached_binary.sha256
                    )
                    if is_different_from_cache:
                        CURRENT_BINARIES.pop(binary.id)
                    else:
                        return cached_binary
                else:
                    # if they have not yet loaded the binary
                    # but our cache is recent enough and not expired, assume cached version is good enough
                    # it will automatically reload when the cache expires
                    # cached_binary will be stale/bad for up to 30min if binary was updated/removed on host system
                    return cached_binary
            else:
                # cached binary is too old, reload it from scratch
                CURRENT_BINARIES.pop(binary.id)
        
        if not binary.abspath or not binary.version or not binary.sha256:
            # if binary was not yet loaded from filesystem, do it now
            # this is expensive, we have to find it's abspath, version, and sha256, but it's necessary
            # to make sure we have a good, up-to-date record of it in the DB & in-memroy cache
            binary = binary.load(fresh=True)

        assert binary.loaded_binprovider and binary.loaded_abspath and binary.loaded_version and binary.loaded_sha256, f'Failed to load binary {binary.name} abspath, version, and sha256'
        
        CURRENT_BINARIES[binary.id], _created = self.update_or_create(
            machine=Machine.objects.current(),
            name=binary.name,
            binprovider=binary.loaded_binprovider.name,
            version=str(binary.loaded_version),
            abspath=str(binary.loaded_abspath),
            sha256=str(binary.loaded_sha256),
        )
        cached_binary = CURRENT_BINARIES[binary.id]
        cached_binary.save()   # populate ABID
        
        # if we get this far make sure DB record matches in-memroy cache
        assert str(cached_binary.binprovider) == str(binary.loaded_binprovider.name)
        assert str(cached_binary.abspath) == str(binary.loaded_abspath)
        assert str(cached_binary.version) == str(binary.loaded_version)
        assert str(cached_binary.sha256) == str(binary.loaded_sha256)
        
        return cached_binary
    


class InstalledBinary(ABIDModel, ModelWithHealthStats):
    abid_prefix = 'bin_'
    abid_ts_src = 'self.machine.created_at'
    abid_uri_src = 'self.machine.guid'
    abid_subtype_src = 'self.binprovider'
    abid_rand_src = 'self.id'
    abid_drift_allowed = False
    
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)

    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    
    # IMMUTABLE PROPERTIES
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, default=None, null=False, blank=True)
    name = models.CharField(max_length=63, default=None, null=False, blank=True)
    binprovider = models.CharField(max_length=31, default=None, null=False, blank=True)
    abspath = models.CharField(max_length=255, default=None, null=False, blank=True)
    version = models.CharField(max_length=32, default=None, null=False, blank=True)
    sha256 = models.CharField(max_length=64, default=None, null=False, blank=True)
    
    # MUTABLE PROPERTIES
    # is_pinned = models.BooleanField(default=False)    # i.e. should this binary superceede other binaries with the same name on the host?
    # is_valid = models.BooleanField(default=True)      # i.e. is this binary still available on the host?
    
    # STATS COUNTERS (from ModelWithHealthStats)
    # num_uses_failed = models.PositiveIntegerField(default=0)
    # num_uses_succeeded = models.PositiveIntegerField(default=0)
    
    objects: InstalledBinaryManager = InstalledBinaryManager()
    
    class Meta:
        verbose_name = 'Installed Binary'
        verbose_name_plural = 'Installed Binaries'
        unique_together = (
            ('machine', 'name', 'binprovider', 'abspath', 'version', 'sha256'),
        )

    def __str__(self) -> str:
        return f'{self.name}@{self.binprovider}+{self.abspath}@{self.version}'
    
    def clean(self, *args, **kwargs) -> None:
        assert self.name or self.abspath
        self.name = str(self.name or self.abspath)
        assert self.name

        if not hasattr(self, 'machine'):
            self.machine = Machine.objects.current()
        if not self.binprovider:
            all_known_binproviders = list(abx.archivebox.use.get_BINPROVIDERS().values())
            binary = BaseBinary(name=self.name, binproviders=all_known_binproviders).load(fresh=True)
            self.binprovider = binary.loaded_binprovider.name if binary.loaded_binprovider else None
        if not self.abspath:
            self.abspath = self.BINPROVIDER.get_abspath(self.name)
        if not self.version:
            self.version = self.BINPROVIDER.get_version(self.name, abspath=self.abspath)
        if not self.sha256:
            self.sha256 = self.BINPROVIDER.get_sha256(self.name, abspath=self.abspath)
            
        super().clean(*args, **kwargs)

    @cached_property
    def BINARY(self) -> BaseBinary:
        for binary in abx.archivebox.use.get_BINARIES().values():
            if binary.name == self.name:
                return binary
        raise Exception(f'Orphaned InstalledBinary {self.name} {self.binprovider} was found in DB, could not find any plugin that defines it')
        # TODO: we could technically reconstruct it from scratch, but why would we ever want to do that?

    @cached_property
    def BINPROVIDER(self) -> BaseBinProvider:
        for binprovider in abx.archivebox.use.get_BINPROVIDERS().values():
            if binprovider.name == self.binprovider:
                return binprovider
        raise Exception(f'Orphaned InstalledBinary(name={self.name}) was found in DB, could not find any plugin that defines BinProvider(name={self.binprovider})')

    # maybe not a good idea to provide this? Binary in DB is a record of the binary's config
    # whereas a loaded binary is a not-yet saved instance that may not have the same config
    # why would we want to load a binary record from the db when it could be freshly loaded?
    def load_from_db(self) -> BaseBinary:
        # TODO: implement defaults arg in pydantic_pkgr
        # return self.BINARY.load(defaults={
        #     'binprovider': self.BINPROVIDER,
        #     'abspath': Path(self.abspath),
        #     'version': self.version,
        #     'sha256': self.sha256,
        # })
        
        return BaseBinary.model_validate({
            **self.BINARY.model_dump(),
            'abspath': self.abspath and Path(self.abspath),
            'version': self.version,
            'sha256': self.sha256,
            'loaded_binprovider': self.BINPROVIDER,
            'binproviders_supported': self.BINARY.binproviders_supported,
            'provider_overrides': self.BINARY.provider_overrides,
        })

    def load_fresh(self) -> BaseBinary:
        return self.BINARY.load(fresh=True)
