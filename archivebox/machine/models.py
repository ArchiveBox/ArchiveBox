__package__ = 'archivebox.machine'

import socket
from uuid import uuid7
from datetime import timedelta

from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property

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


class Machine(ModelWithHealthStats):
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
    config = models.JSONField(default=dict, null=False, blank=True,
        help_text="Machine-specific config overrides (e.g., resolved binary paths like WGET_BINARY)")
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


class NetworkInterface(ModelWithHealthStats):
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


class DependencyManager(models.Manager):
    def get_or_create_for_extractor(self, bin_name: str, bin_providers: str = '*', custom_cmds: dict = None, config: dict = None) -> 'Dependency':
        """Get or create a Dependency for an extractor's binary."""
        dependency, created = self.get_or_create(
            bin_name=bin_name,
            defaults={
                'bin_providers': bin_providers,
                'custom_cmds': custom_cmds or {},
                'config': config or {},
            }
        )
        return dependency


class Dependency(models.Model):
    """
    Defines a binary dependency needed by an extractor.

    This model tracks what binaries need to be installed and how to install them.
    Provider hooks listen for Dependency creation events and attempt installation.

    Example:
        Dependency.objects.get_or_create(
            bin_name='wget',
            bin_providers='apt,brew,nix,custom',
            custom_cmds={
                'apt': 'apt install -y --no-install-recommends wget',
                'brew': 'brew install wget',
                'custom': 'curl https://example.com/get-wget.sh | bash',
            }
        )
    """

    BIN_PROVIDER_CHOICES = (
        ('*', 'Any'),
        ('apt', 'apt'),
        ('brew', 'brew'),
        ('pip', 'pip'),
        ('npm', 'npm'),
        ('gem', 'gem'),
        ('nix', 'nix'),
        ('env', 'env (already in PATH)'),
        ('custom', 'custom'),
    )

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    bin_name = models.CharField(max_length=63, unique=True, db_index=True,
        help_text="Binary executable name (e.g., wget, yt-dlp, chromium)")
    bin_providers = models.CharField(max_length=127, default='*',
        help_text="Comma-separated list of allowed providers: apt,brew,pip,npm,gem,nix,custom or * for any")
    custom_cmds = models.JSONField(default=dict, blank=True,
        help_text="JSON map of provider -> custom install command (e.g., {'apt': 'apt install -y wget'})")
    config = models.JSONField(default=dict, blank=True,
        help_text="JSON map of env var config to use during install")

    objects: DependencyManager = DependencyManager()

    class Meta:
        verbose_name = 'Dependency'
        verbose_name_plural = 'Dependencies'

    def __str__(self) -> str:
        return f'{self.bin_name} (providers: {self.bin_providers})'

    def allows_provider(self, provider: str) -> bool:
        """Check if this dependency allows the given provider."""
        if self.bin_providers == '*':
            return True
        return provider in self.bin_providers.split(',')

    def get_install_cmd(self, provider: str) -> str | None:
        """Get the install command for a provider, or None for default."""
        return self.custom_cmds.get(provider)

    @property
    def installed_binaries(self):
        """Get all InstalledBinary records for this dependency."""
        return InstalledBinary.objects.filter(dependency=self)

    @property
    def is_installed(self) -> bool:
        """Check if at least one valid InstalledBinary exists for this dependency."""
        return self.installed_binaries.filter(abspath__isnull=False).exclude(abspath='').exists()


class InstalledBinaryManager(models.Manager):
    def get_from_db_or_cache(self, name: str, abspath: str = '', version: str = '', sha256: str = '', binprovider: str = 'env') -> 'InstalledBinary':
        """Get or create an InstalledBinary record from the database or cache."""
        global _CURRENT_BINARIES
        cached = _CURRENT_BINARIES.get(name)
        if cached and timezone.now() < cached.modified_at + timedelta(seconds=INSTALLED_BINARY_RECHECK_INTERVAL):
            return cached
        _CURRENT_BINARIES[name], _ = self.update_or_create(
            machine=Machine.objects.current(), name=name, binprovider=binprovider,
            version=version, abspath=abspath, sha256=sha256,
        )
        return _CURRENT_BINARIES[name]

    def get_valid_binary(self, name: str, machine: 'Machine | None' = None) -> 'InstalledBinary | None':
        """Get a valid InstalledBinary for the given name on the current machine, or None if not found."""
        machine = machine or Machine.current()
        return self.filter(
            machine=machine,
            name__iexact=name,
        ).exclude(abspath='').exclude(abspath__isnull=True).order_by('-modified_at').first()


class InstalledBinary(ModelWithHealthStats):
    """
    Tracks an installed binary on a specific machine.

    Each InstalledBinary is optionally linked to a Dependency that defines
    how the binary should be installed. The `is_valid` property indicates
    whether the binary is usable (has both abspath and version).
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, default=None, null=False, blank=True)
    dependency = models.ForeignKey(Dependency, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='installedbinary_set',
        help_text="The Dependency this binary satisfies")
    name = models.CharField(max_length=63, default=None, null=False, blank=True, db_index=True)
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

    @property
    def is_valid(self) -> bool:
        """A binary is valid if it has both abspath and version set."""
        return bool(self.abspath) and bool(self.version)

    @cached_property
    def binary_info(self) -> dict:
        """Return info about the binary."""
        return {
            'name': self.name,
            'abspath': self.abspath,
            'version': self.version,
            'binprovider': self.binprovider,
            'is_valid': self.is_valid,
        }


