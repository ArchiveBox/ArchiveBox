__package__ = 'archivebox.machine'

import sys
import os
import signal
import socket
import subprocess
import multiprocessing

from datetime import timedelta
from pathlib import Path

from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property

import abx
import archivebox

from abx_pkg import Binary, BinProvider
from archivebox.base_models.models import ABIDModel, ABIDField, AutoDateTimeField, ModelWithHealthStats

from .detect import get_host_guid, get_os_info, get_vm_info, get_host_network, get_host_stats

_CURRENT_MACHINE = None                              # global cache for the current machine
_CURRENT_INTERFACE = None                            # global cache for the current network interface
_CURRENT_BINARIES = {}                               # global cache for the currently installed binaries


MACHINE_RECHECK_INTERVAL = 7 * 24 * 60 * 60         # 1 week (how often should we check for OS/hardware changes?)
NETWORK_INTERFACE_RECHECK_INTERVAL = 1 * 60 * 60    # 1 hour (how often should we check for public IP/private IP/DNS changes?)
INSTALLED_BINARY_RECHECK_INTERVAL = 1 * 30 * 60     # 30min  (how often should we check for changes to locally installed binaries?)



class MachineManager(models.Manager):
    def current(self) -> 'Machine':
        return Machine.current()


class Machine(ABIDModel, ModelWithHealthStats):
    """Audit log entry for a physical machine that was used to do archiving."""
    
    abid_prefix = 'mcn_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.guid'
    abid_subtype_src = '"01"'
    abid_rand_src = 'self.id'
    abid_drift_allowed = False
    
    read_only_fields = ('id', 'abid', 'created_at', 'guid', 'hw_in_docker', 'hw_in_vm', 'hw_manufacturer', 'hw_product', 'hw_uuid', 'os_arch', 'os_family')

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

    @classmethod
    def current(cls) -> 'Machine':
        """Get the current machine that ArchiveBox is running on."""
        
        global _CURRENT_MACHINE
        if _CURRENT_MACHINE:
            expires_at = _CURRENT_MACHINE.modified_at + timedelta(seconds=MACHINE_RECHECK_INTERVAL)
            if timezone.now() < expires_at:
                # assume current machine cant change *while archivebox is actively running on it*
                # it's not strictly impossible to swap hardware while code is running,
                # but its rare and unusual so we check only once per week
                # (e.g. VMWare can live-migrate a VM to a new host while it's running)
                return _CURRENT_MACHINE
            else:
                _CURRENT_MACHINE = None
        
        _CURRENT_MACHINE, _created = cls.objects.update_or_create(
            guid=get_host_guid(),
            defaults={
                'hostname': socket.gethostname(),
                **get_os_info(),
                **get_vm_info(),
                'stats': get_host_stats(),
            },
        )        
        _CURRENT_MACHINE.save()  # populate ABID
        
        return _CURRENT_MACHINE



class NetworkInterfaceManager(models.Manager):
    def current(self) -> 'NetworkInterface':
        return NetworkInterface.current()


class NetworkInterface(ABIDModel, ModelWithHealthStats):
    """Audit log entry for a physical network interface / internet connection that was used to do archiving."""
    
    abid_prefix = 'net_'
    abid_ts_src = 'self.machine.created_at'
    abid_uri_src = 'self.machine.guid'
    abid_subtype_src = 'self.iface'
    abid_rand_src = 'self.id'
    abid_drift_allowed = False
    
    read_only_fields = ('id', 'abid', 'created_at', 'machine', 'mac_address', 'ip_public', 'ip_local', 'dns_server')
    
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

    # STATS COUNTERS (inherited from ModelWithHealthStats)
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
        
    @classmethod
    def current(cls) -> 'NetworkInterface':
        """Get the current network interface for the current machine."""
        
        global _CURRENT_INTERFACE
        if _CURRENT_INTERFACE:
            # assume the current network interface (public IP, DNS servers, etc.) wont change more than once per hour
            expires_at = _CURRENT_INTERFACE.modified_at + timedelta(seconds=NETWORK_INTERFACE_RECHECK_INTERVAL)
            if timezone.now() < expires_at:
                return _CURRENT_INTERFACE
            else:
                _CURRENT_INTERFACE = None
        
        machine = Machine.objects.current()
        net_info = get_host_network()
        _CURRENT_INTERFACE, _created = cls.objects.update_or_create(
            machine=machine,
            ip_public=net_info.pop('ip_public'),
            ip_local=net_info.pop('ip_local'),
            mac_address=net_info.pop('mac_address'),
            dns_server=net_info.pop('dns_server'),
            defaults=net_info,
        )
        _CURRENT_INTERFACE.save()  # populate ABID

        return _CURRENT_INTERFACE


class InstalledBinaryManager(models.Manager):
    def get_from_db_or_cache(self, binary: Binary) -> 'InstalledBinary':
        """Get or create an InstalledBinary record for a Binary on the local machine"""
        
        global _CURRENT_BINARIES
        cached_binary = _CURRENT_BINARIES.get(binary.name)
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
                        _CURRENT_BINARIES.pop(binary.name)
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
                _CURRENT_BINARIES.pop(binary.name)
        
        if not binary.abspath or not binary.version or not binary.sha256:
            # if binary was not yet loaded from filesystem, do it now
            # this is expensive, we have to find it's abspath, version, and sha256, but it's necessary
            # to make sure we have a good, up-to-date record of it in the DB & in-memroy cache
            binary = archivebox.pm.hook.binary_load(binary=binary, fresh=True)

        assert binary.loaded_binprovider and binary.loaded_abspath and binary.loaded_version and binary.loaded_sha256, f'Failed to load binary {binary.name} abspath, version, and sha256'
        
        _CURRENT_BINARIES[binary.name], _created = self.update_or_create(
            machine=Machine.objects.current(),
            name=binary.name,
            binprovider=binary.loaded_binprovider.name,
            version=str(binary.loaded_version),
            abspath=str(binary.loaded_abspath),
            sha256=str(binary.loaded_sha256),
        )
        cached_binary = _CURRENT_BINARIES[binary.name]
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
    
    read_only_fields = ('id', 'abid', 'created_at', 'machine', 'name', 'binprovider', 'abspath', 'version', 'sha256')
    
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
    
    # MUTABLE PROPERTIES (TODO)
    # is_pinned = models.BooleanField(default=False)    # i.e. should this binary superceede other binaries with the same name on the host?
    # is_valid = models.BooleanField(default=True)      # i.e. is this binary still available on the host?
    
    # STATS COUNTERS (inherited from ModelWithHealthStats)
    # num_uses_failed = models.PositiveIntegerField(default=0)
    # num_uses_succeeded = models.PositiveIntegerField(default=0)
    
    objects: InstalledBinaryManager = InstalledBinaryManager()
    
    class Meta:
        verbose_name = 'Installed Binary'
        verbose_name_plural = 'Installed Binaries'
        unique_together = (
            ('machine', 'name', 'abspath', 'version', 'sha256'),
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
            all_known_binproviders = list(abx.as_dict(archivebox.pm.hook.get_BINPROVIDERS()).values())
            binary = archivebox.pm.hook.binary_load(binary=Binary(name=self.name, binproviders=all_known_binproviders), fresh=True)
            self.binprovider = binary.loaded_binprovider.name if binary.loaded_binprovider else None
        if not self.abspath:
            self.abspath = self.BINPROVIDER.get_abspath(self.name)
        if not self.version:
            self.version = self.BINPROVIDER.get_version(self.name, abspath=self.abspath)
        if not self.sha256:
            self.sha256 = self.BINPROVIDER.get_sha256(self.name, abspath=self.abspath)
            
        super().clean(*args, **kwargs)

    @cached_property
    def BINARY(self) -> Binary:
        for binary in abx.as_dict(archivebox.pm.hook.get_BINARIES()).values():
            if binary.name == self.name:
                return binary
        raise Exception(f'Orphaned InstalledBinary {self.name} {self.binprovider} was found in DB, could not find any plugin that defines it')
        # TODO: we could technically reconstruct it from scratch, but why would we ever want to do that?

    @cached_property
    def BINPROVIDER(self) -> BinProvider:
        for binprovider in abx.as_dict(archivebox.pm.hook.get_BINPROVIDERS()).values():
            if binprovider.name == self.binprovider:
                return binprovider
        raise Exception(f'Orphaned InstalledBinary(name={self.name}) was found in DB, could not find any plugin that defines BinProvider(name={self.binprovider})')

    # maybe not a good idea to provide this? Binary in DB is a record of the binary's config
    # whereas a loaded binary is a not-yet saved instance that may not have the same config
    # why would we want to load a binary record from the db when it could be freshly loaded?
    def load_from_db(self) -> Binary:
        # TODO: implement defaults arg in abx_pkg
        # return self.BINARY.load(defaults={
        #     'binprovider': self.BINPROVIDER,
        #     'abspath': Path(self.abspath),
        #     'version': self.version,
        #     'sha256': self.sha256,
        # })
        
        return Binary.model_validate({
            **self.BINARY.model_dump(),
            'abspath': self.abspath and Path(self.abspath),
            'version': self.version,
            'sha256': self.sha256,
            'loaded_binprovider': self.BINPROVIDER,
            'binproviders_supported': self.BINARY.binproviders_supported,
            'overrides': self.BINARY.overrides,
        })

    def load_fresh(self) -> Binary:
        return archivebox.pm.hook.binary_load(binary=self.BINARY, fresh=True)




def spawn_process(proc_id: str):
    proc = Process.objects.get(id=proc_id)
    proc.spawn()
    

class ProcessManager(models.Manager):
    pass

class ProcessQuerySet(models.QuerySet):
    """
    Enhanced QuerySet for Process model, usage:
        Process.objects.queued() -> QuerySet[Process] [Process(pid=None, returncode=None), Process(pid=None, returncode=None)]
        Process.objects.running() -> QuerySet[Process] [Process(pid=123, returncode=None), Process(pid=456, returncode=None)]
        Process.objects.exited() -> QuerySet[Process] [Process(pid=789, returncode=0), Process(pid=101, returncode=1)]
        Process.objects.running().pids() -> [456]
        Process.objects.kill() -> 1
    """
    
    def queued(self):
        return self.filter(pid__isnull=True, returncode__isnull=True)
    
    def running(self):
        return self.filter(pid__isnull=False, returncode__isnull=True)
            
    def exited(self):
        return self.filter(returncode__isnull=False)
    
    def kill(self):
        total_killed = 0
        for proc in self.running():
            proc.kill()
            total_killed += 1
        return total_killed
    
    def pids(self):
        return self.values_list('pid', flat=True)


class Process(ABIDModel):
    abid_prefix = 'pid_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.cmd'
    abid_subtype_src = 'self.actor_type or "00"'
    abid_rand_src = 'self.id'
    abid_drift_allowed = False
    
    read_only_fields = ('id', 'abid', 'created_at', 'cmd', 'cwd', 'actor_type', 'timeout')
    
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)
    
    # immutable state
    cmd = models.JSONField(default=list)                             # shell argv
    cwd = models.CharField(max_length=255)                           # working directory
    actor_type = models.CharField(max_length=255, null=True)         # python ActorType that this process is running
    timeout = models.PositiveIntegerField(null=True, default=None)   # seconds to wait before killing the process if it's still running
    
    created_at = models.DateTimeField(null=False, default=timezone.now, editable=False)
    modified_at = models.DateTimeField(null=False, default=timezone.now, editable=False)

    # mutable fields
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE)
    pid = models.IntegerField(null=True)
    launched_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    returncode = models.IntegerField(null=True)
    stdout = models.TextField(default='', null=False)
    stderr = models.TextField(default='', null=False)

    machine_id: str

    # optional mutable state that can be used to trace what the process is doing
    # active_event = models.ForeignKey('Event', null=True, on_delete=models.SET_NULL)
    
    emitted_events: models.RelatedManager['Event']
    claimed_events: models.RelatedManager['Event']
    
    objects: ProcessManager = ProcessManager.from_queryset(ProcessQuerySet)()

    @classmethod
    def current(cls) -> 'Process':
        proc_id = os.environ.get('PROCESS_ID', '').strip()
        if not proc_id:
            proc = cls.objects.create(
                cmd=sys.argv,
                cwd=os.getcwd(),
                actor_type=None,
                timeout=None,
                machine=Machine.objects.current(),
                pid=os.getpid(),
                launched_at=timezone.now(),
                finished_at=None,
                returncode=None,
                stdout='',
                stderr='',
            )
            os.environ['PROCESS_ID'] = str(proc.id)
            return proc
        
        proc = cls.objects.get(id=proc_id)
        if proc.pid:
            assert os.getpid() == proc.pid, f'Process ID mismatch: {proc.pid} != {os.getpid()}'
        else:
            proc.pid = os.getpid()

        proc.machine = Machine.current()
        proc.cwd = os.getcwd()    
        proc.cmd = sys.argv
        proc.launched_at = proc.launched_at or timezone.now()
        proc.save()
        
        return proc

    @classmethod
    def create_and_fork(cls, **kwargs):
        proc = cls.objects.create(**kwargs)
        proc.fork()
        return proc

    def fork(self):
        if self.pid:
            raise Exception(f'Process is already running, cannot fork again: {self}')
        
        # fork the process in the background
        multiprocessing.Process(target=spawn_process, args=(self.id,)).start()

    def spawn(self):
        if self.pid:
            raise Exception(f'Process already running, cannot spawn again: {self}')
        
        # spawn the process in the foreground and block until it exits
        proc = subprocess.Popen(self.cmd, cwd=self.cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.pid = proc.pid
        self.launched_at = timezone.now()
        self.save()
        # Event.dispatch('PROC_UPDATED', {'process_id': self.id})
        
        # block until the process exits
        proc.wait()
        self.finished_at = timezone.now()
        self.returncode = proc.returncode
        self.stdout = proc.stdout.read()
        self.stderr = proc.stderr.read()
        self.pid = None
        self.save()
        # Event.dispatch('PROC_UPDATED', {'process_id': self.id})
        
    def kill(self):
        if not self.is_running: return
        assert self.machine == Machine.current(), f'Cannot kill actor on another machine: {self.machine_id} != {Machine.current().id}'
        
        os.kill(self.pid, signal.SIGKILL)
        self.pid = None
        self.save()
        # Event.dispatch('PROC_UPDATED', {'process_id': self.id})

    @property
    def is_pending(self):
        return (self.pid is None) and (self.returncode is None)

    @property
    def is_running(self):
        return (self.pid is not None) and (self.returncode is None)
    
    @property
    def is_failed(self):
        return self.returncode not in (None, 0)
    
    @property
    def is_succeeded(self):
        return self.returncode == 0
    
    # @property
    # def is_idle(self):
    #     if not self.actor_type:
    #         raise Exception(f'Process {self.id} has no actor_type set, can only introspect active events if Process.actor_type is set to the Actor its running')
    #     return self.active_event is None

