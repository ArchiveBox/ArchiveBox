__package__ = 'archivebox.machine'

import sys
import os
import signal
import socket
import subprocess
import multiprocessing
from uuid import uuid7
from datetime import timedelta
from pathlib import Path

from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property

import abx
import archivebox
from abx_pkg import Binary, BinProvider
from archivebox.base_models.models import ModelWithHealthStats
from .detect import get_host_guid, get_os_info, get_vm_info, get_host_network, get_host_stats

_CURRENT_MACHINE = None
_CURRENT_INTERFACE = None
_CURRENT_BINARIES = {}

MACHINE_RECHECK_INTERVAL = 7 * 24 * 60 * 60
NETWORK_INTERFACE_RECHECK_INTERVAL = 1 * 60 * 60
INSTALLED_BINARY_RECHECK_INTERVAL = 1 * 30 * 60


class MachineManager(models.Manager):
    def current(self) -> 'Machine':
        return Machine.current()


class Machine(models.Model, ModelWithHealthStats):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    guid = models.CharField(max_length=64, default=None, null=False, unique=True, editable=False)
    hostname = models.CharField(max_length=63, default=None, null=False)
    hw_in_docker = models.BooleanField(default=False, null=False)
    hw_in_vm = models.BooleanField(default=False, null=False)
    hw_manufacturer = models.CharField(max_length=63, default=None, null=False)
    hw_product = models.CharField(max_length=63, default=None, null=False)
    hw_uuid = models.CharField(max_length=255, default=None, null=False)
    os_arch = models.CharField(max_length=15, default=None, null=False)
    os_family = models.CharField(max_length=15, default=None, null=False)
    os_platform = models.CharField(max_length=63, default=None, null=False)
    os_release = models.CharField(max_length=63, default=None, null=False)
    os_kernel = models.CharField(max_length=255, default=None, null=False)
    stats = models.JSONField(default=dict, null=False)
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)

    objects: MachineManager = MachineManager()
    networkinterface_set: models.Manager['NetworkInterface']

    @classmethod
    def current(cls) -> 'Machine':
        global _CURRENT_MACHINE
        if _CURRENT_MACHINE:
            if timezone.now() < _CURRENT_MACHINE.modified_at + timedelta(seconds=MACHINE_RECHECK_INTERVAL):
                return _CURRENT_MACHINE
            _CURRENT_MACHINE = None
        _CURRENT_MACHINE, _ = cls.objects.update_or_create(
            guid=get_host_guid(),
            defaults={'hostname': socket.gethostname(), **get_os_info(), **get_vm_info(), 'stats': get_host_stats()},
        )
        return _CURRENT_MACHINE


class NetworkInterfaceManager(models.Manager):
    def current(self) -> 'NetworkInterface':
        return NetworkInterface.current()


class NetworkInterface(models.Model, ModelWithHealthStats):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, default=None, null=False)
    mac_address = models.CharField(max_length=17, default=None, null=False, editable=False)
    ip_public = models.GenericIPAddressField(default=None, null=False, editable=False)
    ip_local = models.GenericIPAddressField(default=None, null=False, editable=False)
    dns_server = models.GenericIPAddressField(default=None, null=False, editable=False)
    hostname = models.CharField(max_length=63, default=None, null=False)
    iface = models.CharField(max_length=15, default=None, null=False)
    isp = models.CharField(max_length=63, default=None, null=False)
    city = models.CharField(max_length=63, default=None, null=False)
    region = models.CharField(max_length=63, default=None, null=False)
    country = models.CharField(max_length=63, default=None, null=False)
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)

    objects: NetworkInterfaceManager = NetworkInterfaceManager()

    class Meta:
        unique_together = (('machine', 'ip_public', 'ip_local', 'mac_address', 'dns_server'),)

    @classmethod
    def current(cls) -> 'NetworkInterface':
        global _CURRENT_INTERFACE
        if _CURRENT_INTERFACE:
            if timezone.now() < _CURRENT_INTERFACE.modified_at + timedelta(seconds=NETWORK_INTERFACE_RECHECK_INTERVAL):
                return _CURRENT_INTERFACE
            _CURRENT_INTERFACE = None
        machine = Machine.objects.current()
        net_info = get_host_network()
        _CURRENT_INTERFACE, _ = cls.objects.update_or_create(
            machine=machine, ip_public=net_info.pop('ip_public'), ip_local=net_info.pop('ip_local'),
            mac_address=net_info.pop('mac_address'), dns_server=net_info.pop('dns_server'), defaults=net_info,
        )
        return _CURRENT_INTERFACE


class InstalledBinaryManager(models.Manager):
    def get_from_db_or_cache(self, binary: Binary) -> 'InstalledBinary':
        global _CURRENT_BINARIES
        cached = _CURRENT_BINARIES.get(binary.name)
        if cached and timezone.now() < cached.modified_at + timedelta(seconds=INSTALLED_BINARY_RECHECK_INTERVAL):
            return cached
        if not binary.abspath or not binary.version or not binary.sha256:
            binary = archivebox.pm.hook.binary_load(binary=binary, fresh=True)
        _CURRENT_BINARIES[binary.name], _ = self.update_or_create(
            machine=Machine.objects.current(), name=binary.name, binprovider=binary.loaded_binprovider.name,
            version=str(binary.loaded_version), abspath=str(binary.loaded_abspath), sha256=str(binary.loaded_sha256),
        )
        return _CURRENT_BINARIES[binary.name]


class InstalledBinary(models.Model, ModelWithHealthStats):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, default=None, null=False, blank=True)
    name = models.CharField(max_length=63, default=None, null=False, blank=True)
    binprovider = models.CharField(max_length=31, default=None, null=False, blank=True)
    abspath = models.CharField(max_length=255, default=None, null=False, blank=True)
    version = models.CharField(max_length=32, default=None, null=False, blank=True)
    sha256 = models.CharField(max_length=64, default=None, null=False, blank=True)
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)

    objects: InstalledBinaryManager = InstalledBinaryManager()

    class Meta:
        verbose_name = 'Installed Binary'
        verbose_name_plural = 'Installed Binaries'
        unique_together = (('machine', 'name', 'abspath', 'version', 'sha256'),)

    def __str__(self) -> str:
        return f'{self.name}@{self.binprovider}+{self.abspath}@{self.version}'

    @cached_property
    def BINARY(self) -> Binary:
        for binary in abx.as_dict(archivebox.pm.hook.get_BINARIES()).values():
            if binary.name == self.name:
                return binary
        raise Exception(f'Binary {self.name} not found')

    @cached_property
    def BINPROVIDER(self) -> BinProvider:
        for bp in abx.as_dict(archivebox.pm.hook.get_BINPROVIDERS()).values():
            if bp.name == self.binprovider:
                return bp
        raise Exception(f'BinProvider {self.binprovider} not found')


def spawn_process(proc_id: str):
    Process.objects.get(id=proc_id).spawn()


class ProcessManager(models.Manager):
    pass


class ProcessQuerySet(models.QuerySet):
    def queued(self):
        return self.filter(pid__isnull=True, returncode__isnull=True)

    def running(self):
        return self.filter(pid__isnull=False, returncode__isnull=True)

    def exited(self):
        return self.filter(returncode__isnull=False)

    def kill(self):
        count = 0
        for proc in self.running():
            proc.kill()
            count += 1
        return count

    def pids(self):
        return self.values_list('pid', flat=True)


class Process(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    cmd = models.JSONField(default=list)
    cwd = models.CharField(max_length=255)
    actor_type = models.CharField(max_length=255, null=True)
    timeout = models.PositiveIntegerField(null=True, default=None)
    created_at = models.DateTimeField(null=False, default=timezone.now, editable=False)
    modified_at = models.DateTimeField(null=False, default=timezone.now, editable=False)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE)
    pid = models.IntegerField(null=True)
    launched_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    returncode = models.IntegerField(null=True)
    stdout = models.TextField(default='', null=False)
    stderr = models.TextField(default='', null=False)

    objects: ProcessManager = ProcessManager.from_queryset(ProcessQuerySet)()

    @classmethod
    def current(cls) -> 'Process':
        proc_id = os.environ.get('PROCESS_ID', '').strip()
        if not proc_id:
            proc = cls.objects.create(
                cmd=sys.argv, cwd=os.getcwd(), machine=Machine.objects.current(),
                pid=os.getpid(), launched_at=timezone.now(),
            )
            os.environ['PROCESS_ID'] = str(proc.id)
            return proc
        proc = cls.objects.get(id=proc_id)
        proc.pid = proc.pid or os.getpid()
        proc.machine = Machine.current()
        proc.cwd = os.getcwd()
        proc.cmd = sys.argv
        proc.launched_at = proc.launched_at or timezone.now()
        proc.save()
        return proc

    def fork(self):
        if self.pid:
            raise Exception(f'Process already running: {self}')
        multiprocessing.Process(target=spawn_process, args=(self.id,)).start()

    def spawn(self):
        if self.pid:
            raise Exception(f'Process already running: {self}')
        proc = subprocess.Popen(self.cmd, cwd=self.cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.pid = proc.pid
        self.launched_at = timezone.now()
        self.save()
        proc.wait()
        self.finished_at = timezone.now()
        self.returncode = proc.returncode
        self.stdout = proc.stdout.read()
        self.stderr = proc.stderr.read()
        self.pid = None
        self.save()

    def kill(self):
        if self.pid and self.returncode is None:
            os.kill(self.pid, signal.SIGKILL)
            self.pid = None
            self.save()

    @property
    def is_running(self):
        return self.pid is not None and self.returncode is None
