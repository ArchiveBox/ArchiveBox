__package__ = 'archivebox.machine'

import os
import sys
import socket
from pathlib import Path
from archivebox.uuid_compat import uuid7
from datetime import timedelta, datetime

from statemachine import State, registry

from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property

from archivebox.base_models.models import ModelWithHealthStats
from archivebox.workers.models import BaseStateMachine, ModelWithStateMachine
from .detect import get_host_guid, get_os_info, get_vm_info, get_host_network, get_host_stats

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

_CURRENT_MACHINE = None
_CURRENT_INTERFACE = None
_CURRENT_BINARIES = {}
_CURRENT_PROCESS = None

MACHINE_RECHECK_INTERVAL = 7 * 24 * 60 * 60
NETWORK_INTERFACE_RECHECK_INTERVAL = 1 * 60 * 60
BINARY_RECHECK_INTERVAL = 1 * 30 * 60
PROCESS_RECHECK_INTERVAL = 60  # Re-validate every 60 seconds
PID_REUSE_WINDOW = timedelta(hours=24)  # Max age for considering a PID match valid
START_TIME_TOLERANCE = 5.0  # Seconds tolerance for start time matching


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
    stats = models.JSONField(default=dict, null=True, blank=True)
    config = models.JSONField(default=dict, null=True, blank=True,
        help_text="Machine-specific config overrides (e.g., resolved binary paths like WGET_BINARY)")
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)

    objects: MachineManager = MachineManager()
    networkinterface_set: models.Manager['NetworkInterface']

    class Meta:
        app_label = 'machine'

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

    def to_json(self) -> dict:
        """
        Convert Machine model instance to a JSON-serializable dict.
        """
        from archivebox.config import VERSION
        return {
            'type': 'Machine',
            'schema_version': VERSION,
            'id': str(self.id),
            'guid': self.guid,
            'hostname': self.hostname,
            'hw_in_docker': self.hw_in_docker,
            'hw_in_vm': self.hw_in_vm,
            'hw_manufacturer': self.hw_manufacturer,
            'hw_product': self.hw_product,
            'hw_uuid': self.hw_uuid,
            'os_arch': self.os_arch,
            'os_family': self.os_family,
            'os_platform': self.os_platform,
            'os_kernel': self.os_kernel,
            'os_release': self.os_release,
            'stats': self.stats,
            'config': self.config or {},
        }

    @staticmethod
    def from_json(record: dict, overrides: dict = None):
        """
        Update Machine config from JSON dict.

        Args:
            record: JSON dict with 'config': {key: value} patch
            overrides: Not used

        Returns:
            Machine instance or None
        """
        config_patch = record.get('config')
        if isinstance(config_patch, dict) and config_patch:
            machine = Machine.current()
            if not machine.config:
                machine.config = {}
            machine.config.update(config_patch)
            machine.save(update_fields=['config'])
            return machine
        return None


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
    # num_uses_failed = models.PositiveIntegerField(default=0)  # from ModelWithHealthStats
    # num_uses_succeeded = models.PositiveIntegerField(default=0)  # from ModelWithHealthStats

    objects: NetworkInterfaceManager = NetworkInterfaceManager()

    class Meta:
        app_label = 'machine'
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



class BinaryManager(models.Manager):
    def get_from_db_or_cache(self, name: str, abspath: str = '', version: str = '', sha256: str = '', binprovider: str = 'env') -> 'Binary':
        """Get or create an Binary record from the database or cache."""
        global _CURRENT_BINARIES
        cached = _CURRENT_BINARIES.get(name)
        if cached and timezone.now() < cached.modified_at + timedelta(seconds=BINARY_RECHECK_INTERVAL):
            return cached
        _CURRENT_BINARIES[name], _ = self.update_or_create(
            machine=Machine.objects.current(), name=name, binprovider=binprovider,
            version=version, abspath=abspath, sha256=sha256,
        )
        return _CURRENT_BINARIES[name]

    def get_valid_binary(self, name: str, machine: 'Machine | None' = None) -> 'Binary | None':
        """Get a valid Binary for the given name on the current machine, or None if not found."""
        machine = machine or Machine.current()
        return self.filter(
            machine=machine,
            name__iexact=name,
        ).exclude(abspath='').exclude(abspath__isnull=True).order_by('-modified_at').first()


class Binary(ModelWithHealthStats, ModelWithStateMachine):
    """
    Tracks a binary on a specific machine.

    Simple state machine with 2 states:
    - queued: Binary needs to be installed
    - installed: Binary installed successfully (abspath, version, sha256 populated)

    Installation is synchronous during queued→installed transition.
    If installation fails, Binary stays in queued with retry_at set for later retry.

    State machine calls run() which executes on_Binary__install_* hooks
    to install the binary using the specified providers.
    """

    class StatusChoices(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        INSTALLED = 'installed', 'Installed'

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, null=False)

    # Binary metadata
    name = models.CharField(max_length=63, default='', null=False, blank=True, db_index=True)
    binproviders = models.CharField(max_length=127, default='env', null=False, blank=True,
        help_text="Comma-separated list of allowed providers: apt,brew,pip,npm,env")
    overrides = models.JSONField(default=dict, blank=True,
        help_text="Provider-specific overrides: {'apt': {'packages': ['pkg']}, ...}")

    # Installation results (populated after installation)
    binprovider = models.CharField(max_length=31, default='', null=False, blank=True,
        help_text="Provider that successfully installed this binary")
    abspath = models.CharField(max_length=255, default='', null=False, blank=True)
    version = models.CharField(max_length=32, default='', null=False, blank=True)
    sha256 = models.CharField(max_length=64, default='', null=False, blank=True)

    # State machine fields
    status = ModelWithStateMachine.StatusField(choices=StatusChoices.choices, default=StatusChoices.QUEUED, max_length=16)
    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now,
        help_text="When to retry this binary installation")

    # Health stats
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)

    state_machine_name: str = 'archivebox.machine.models.BinaryMachine'
    active_state: str = StatusChoices.QUEUED

    objects: BinaryManager = BinaryManager()

    class Meta:
        app_label = 'machine'
        verbose_name = 'Binary'
        verbose_name_plural = 'Binaries'
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

    @property
    def output_dir(self) -> Path:
        """
        Get output directory for this binary's hook logs.
        Path: data/machines/{machine_uuid}/binaries/{binary_name}/{binary_uuid}
        """
        from django.conf import settings
        return Path(settings.DATA_DIR) / 'machines' / str(self.machine_id) / 'binaries' / self.name / str(self.id)

    def to_json(self) -> dict:
        """
        Convert Binary model instance to a JSON-serializable dict.
        """
        from archivebox.config import VERSION
        return {
            'type': 'Binary',
            'schema_version': VERSION,
            'id': str(self.id),
            'machine_id': str(self.machine_id),
            'name': self.name,
            'binprovider': self.binprovider,
            'abspath': self.abspath,
            'version': self.version,
            'sha256': self.sha256,
            'status': self.status,
        }

    @staticmethod
    def from_json(record: dict, overrides: dict = None):
        """
        Create/update Binary from JSON dict.

        Handles two cases:
        1. From binaries.json: creates queued binary with name, binproviders, overrides
        2. From hook output: updates binary with abspath, version, sha256, binprovider

        Args:
            record: JSON dict with 'name' and either:
                    - 'binproviders', 'overrides' (from binaries.json)
                    - 'abspath', 'version', 'sha256', 'binprovider' (from hook output)
            overrides: Not used

        Returns:
            Binary instance or None
        """
        name = record.get('name')
        if not name:
            return None

        machine = Machine.current()
        overrides = overrides or {}

        # Case 1: Already installed (from on_Crawl hooks) - has abspath AND binproviders
        # This happens when on_Crawl hooks detect already-installed binaries
        abspath = record.get('abspath')
        version = record.get('version')
        binproviders = record.get('binproviders')

        if abspath and version and binproviders:
            # Binary is already installed, create INSTALLED record with binproviders filter
            binary, _ = Binary.objects.update_or_create(
                machine=machine,
                name=name,
                defaults={
                    'abspath': abspath,
                    'version': version,
                    'sha256': record.get('sha256', ''),
                    'binprovider': record.get('binprovider', 'env'),
                    'binproviders': binproviders,  # Preserve the filter
                    'status': Binary.StatusChoices.INSTALLED,
                    'retry_at': None,
                }
            )
            return binary

        # Case 2: From binaries.json - create queued binary (needs installation)
        if 'binproviders' in record or ('overrides' in record and not abspath):
            binary, created = Binary.objects.get_or_create(
                machine=machine,
                name=name,
                defaults={
                    'binproviders': record.get('binproviders', 'env'),
                    'overrides': record.get('overrides', {}),
                    'status': Binary.StatusChoices.QUEUED,
                    'retry_at': timezone.now(),
                }
            )
            return binary

        # Case 3: From on_Binary__install hook output - update with installation results
        if abspath and version:
            binary, _ = Binary.objects.update_or_create(
                machine=machine,
                name=name,
                defaults={
                    'abspath': abspath,
                    'version': version,
                    'sha256': record.get('sha256', ''),
                    'binprovider': record.get('binprovider', 'env'),
                    'status': Binary.StatusChoices.INSTALLED,
                    'retry_at': None,
                }
            )
            return binary

        return None

    def update_and_requeue(self, **kwargs):
        """
        Update binary fields and requeue for worker state machine.

        Sets modified_at to ensure workers pick up changes.
        Always saves the model after updating.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.modified_at = timezone.now()
        self.save()

    def run(self):
        """
        Execute binary installation by running on_Binary__install_* hooks.

        Called by BinaryMachine when entering 'started' state.
        Runs ALL on_Binary__install_* hooks - each hook checks binproviders
        and decides if it can handle this binary. First hook to succeed wins.
        Updates status to SUCCEEDED or FAILED based on hook output.
        """
        import json
        from archivebox.hooks import discover_hooks, run_hook
        from archivebox.config.configset import get_config

        # Get merged config (Binary doesn't have crawl/snapshot context)
        config = get_config()

        # Create output directory
        output_dir = self.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        # Discover ALL on_Binary__install_* hooks
        hooks = discover_hooks('Binary', config=config)
        if not hooks:
            # No hooks available - stay queued, will retry later
            return

        # Run each hook - they decide if they can handle this binary
        for hook in hooks:
            plugin_name = hook.parent.name
            plugin_output_dir = output_dir / plugin_name
            plugin_output_dir.mkdir(parents=True, exist_ok=True)

            # Build kwargs for hook
            hook_kwargs = {
                'binary_id': str(self.id),
                'machine_id': str(self.machine_id),
                'name': self.name,
                'binproviders': self.binproviders,
            }

            # Add overrides as JSON string if present
            if self.overrides:
                hook_kwargs['overrides'] = json.dumps(self.overrides)

            # Run the hook
            process = run_hook(
                hook,
                output_dir=plugin_output_dir,
                config=config,
                timeout=600,  # 10 min timeout for binary installation
                **hook_kwargs
            )

            # Background hook (unlikely for binary installation, but handle it)
            if process is None:
                continue

            # Failed or skipped hook - try next one
            if process.exit_code != 0:
                continue

            # Parse JSONL output to check for successful installation
            from archivebox.hooks import extract_records_from_process, process_hook_records
            records = extract_records_from_process(process)
            if records:
                process_hook_records(records, overrides={})
            binary_records = [
                record for record in records
                if record.get('type') == 'Binary' and record.get('abspath')
            ]
            if binary_records:
                record = binary_records[0]
                # Update self from successful installation
                self.abspath = record['abspath']
                self.version = record.get('version', '')
                self.sha256 = record.get('sha256', '')
                self.binprovider = record.get('binprovider', 'env')
                self.status = self.StatusChoices.INSTALLED
                self.save()

                # Symlink binary into LIB_BIN_DIR if configured
                from django.conf import settings
                lib_bin_dir = getattr(settings, 'LIB_BIN_DIR', None)
                if lib_bin_dir:
                    self.symlink_to_lib_bin(lib_bin_dir)

                return

        # No hook succeeded - leave status as QUEUED (will retry later)
        # Don't set to FAILED since we don't have that status anymore

    def cleanup(self):
        """
        Clean up background binary installation hooks.

        Called by state machine if needed (not typically used for binaries
        since installations are foreground, but included for consistency).
        """
        from pathlib import Path

        # Kill any background binary installation hooks using Process records
        # (rarely used since binary installations are typically foreground)
        running_hooks = Process.objects.filter(
            binary=self,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
        )

        for process in running_hooks:
            killed_count = process.kill_tree(graceful_timeout=2.0)
            if killed_count > 0:
                print(f'[yellow]🔪 Killed {killed_count} binary installation hook process(es)[/yellow]')

        # Clean up .pid files from output directory
        output_dir = self.output_dir
        if output_dir.exists():
            for pid_file in output_dir.glob('**/*.pid'):
                pid_file.unlink(missing_ok=True)

    def symlink_to_lib_bin(self, lib_bin_dir: str | Path) -> Path | None:
        """
        Symlink this binary into LIB_BIN_DIR for unified PATH management.

        After a binary is installed by any binprovider (pip, npm, brew, apt, etc),
        we symlink it into LIB_BIN_DIR so that:
        1. All binaries can be found in a single directory
        2. PATH only needs LIB_BIN_DIR prepended (not multiple provider-specific paths)
        3. Binary priorities are clear (symlink points to the canonical install location)

        Args:
            lib_bin_dir: Path to LIB_BIN_DIR (e.g., /data/lib/arm64-darwin/bin)

        Returns:
            Path to the created symlink, or None if symlinking failed

        Example:
            >>> binary = Binary.objects.get(name='yt-dlp')
            >>> binary.symlink_to_lib_bin('/data/lib/arm64-darwin/bin')
            Path('/data/lib/arm64-darwin/bin/yt-dlp')
        """
        import sys
        from pathlib import Path

        if not self.abspath:
            return None

        binary_abspath = Path(self.abspath).resolve()
        lib_bin_dir = Path(lib_bin_dir).resolve()

        # Create LIB_BIN_DIR if it doesn't exist
        try:
            lib_bin_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            print(f"Failed to create LIB_BIN_DIR {lib_bin_dir}: {e}", file=sys.stderr)
            return None

        # Get binary name (last component of path)
        binary_name = binary_abspath.name
        symlink_path = lib_bin_dir / binary_name

        # Remove existing symlink/file if it exists
        if symlink_path.exists() or symlink_path.is_symlink():
            try:
                # Check if it's already pointing to the right place
                if symlink_path.is_symlink() and symlink_path.resolve() == binary_abspath:
                    # Already correctly symlinked, nothing to do
                    return symlink_path

                # Remove old symlink/file
                symlink_path.unlink()
            except (OSError, PermissionError) as e:
                print(f"Failed to remove existing file at {symlink_path}: {e}", file=sys.stderr)
                return None

        # Create new symlink
        try:
            symlink_path.symlink_to(binary_abspath)
            print(f"Symlinked {binary_name} -> {symlink_path}", file=sys.stderr)
            return symlink_path
        except (OSError, PermissionError) as e:
            print(f"Failed to create symlink {symlink_path} -> {binary_abspath}: {e}", file=sys.stderr)
            return None


# =============================================================================
# Process Model
# =============================================================================

class ProcessManager(models.Manager):
    """Manager for Process model."""

    def current(self) -> 'Process':
        """Get the Process record for the current OS process."""
        return Process.current()

    def get_by_pid(self, pid: int, machine: 'Machine' = None) -> 'Process | None':
        """
        Find a Process by PID with proper validation against PID reuse.

        IMPORTANT: PIDs are reused by the OS! This method:
        1. Filters by machine (required - PIDs are only unique per machine)
        2. Filters by time window (processes older than 24h are stale)
        3. Validates via psutil that start times match

        Args:
            pid: OS process ID
            machine: Machine instance (defaults to current machine)

        Returns:
            Process if found and validated, None otherwise
        """
        if not PSUTIL_AVAILABLE:
            return None

        machine = machine or Machine.current()

        # Get the actual process start time from OS
        try:
            os_proc = psutil.Process(pid)
            os_start_time = os_proc.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Process doesn't exist - any DB record with this PID is stale
            return None

        # Query candidates: same machine, same PID, recent, still RUNNING
        candidates = self.filter(
            machine=machine,
            pid=pid,
            status=Process.StatusChoices.RUNNING,
            started_at__gte=timezone.now() - PID_REUSE_WINDOW,
        ).order_by('-started_at')

        for candidate in candidates:
            # Validate start time matches (within tolerance)
            if candidate.started_at:
                db_start_time = candidate.started_at.timestamp()
                if abs(db_start_time - os_start_time) < START_TIME_TOLERANCE:
                    return candidate

        return None

    def create_for_archiveresult(self, archiveresult, **kwargs):
        """
        Create a Process record for an ArchiveResult.

        Called during migration and when creating new ArchiveResults.
        """
        # Defaults from ArchiveResult if not provided
        defaults = {
            'machine': Machine.current(),
            'pwd': kwargs.get('pwd') or str(archiveresult.snapshot.output_dir / archiveresult.plugin),
            'cmd': kwargs.get('cmd') or [],
            'status': 'queued',
            'timeout': kwargs.get('timeout', 120),
            'env': kwargs.get('env', {}),
        }
        defaults.update(kwargs)

        process = self.create(**defaults)
        return process


class Process(models.Model):
    """
    Tracks a single OS process execution.

    Process represents the actual subprocess spawned to execute a hook.
    One Process can optionally be associated with an ArchiveResult (via OneToOne),
    but Process can also exist standalone for internal operations.

    Follows the unified state machine pattern:
    - queued: Process ready to launch
    - running: Process actively executing
    - exited: Process completed (check exit_code for success/failure)

    State machine calls launch() to spawn the process and monitors its lifecycle.
    """

    class StatusChoices(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        RUNNING = 'running', 'Running'
        EXITED = 'exited', 'Exited'

    class TypeChoices(models.TextChoices):
        SUPERVISORD = 'supervisord', 'Supervisord'
        ORCHESTRATOR = 'orchestrator', 'Orchestrator'
        WORKER = 'worker', 'Worker'
        CLI = 'cli', 'CLI'
        HOOK = 'hook', 'Hook'
        BINARY = 'binary', 'Binary'

    # Primary fields
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    # Machine FK - required (every process runs on a machine)
    machine = models.ForeignKey(
        Machine,
        on_delete=models.CASCADE,
        null=False,
        related_name='process_set',
        help_text='Machine where this process executed'
    )

    # Parent process (optional)
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='children',
        help_text='Parent process that spawned this process'
    )

    # Process type (cli, worker, orchestrator, binary, supervisord)
    process_type = models.CharField(
        max_length=16,
        choices=TypeChoices.choices,
        default=TypeChoices.CLI,
        db_index=True,
        help_text='Type of process (cli, worker, orchestrator, binary, supervisord)'
    )

    # Worker type (only for WORKER processes: crawl, snapshot, archiveresult)
    worker_type = models.CharField(
        max_length=32,
        default='',
        null=False,
        blank=True,
        db_index=True,
        help_text='Worker type name for WORKER processes (crawl, snapshot, archiveresult)'
    )

    # Execution metadata
    pwd = models.CharField(max_length=512, default='', null=False, blank=True,
        help_text='Working directory for process execution')
    cmd = models.JSONField(default=list, null=False, blank=True,
        help_text='Command as array of arguments')
    env = models.JSONField(default=dict, null=False, blank=True,
        help_text='Environment variables for process')
    timeout = models.IntegerField(default=120, null=False,
        help_text='Timeout in seconds')

    # Process results
    pid = models.IntegerField(default=None, null=True, blank=True,
        help_text='OS process ID')
    exit_code = models.IntegerField(default=None, null=True, blank=True,
        help_text='Process exit code (0 = success)')
    stdout = models.TextField(default='', null=False, blank=True,
        help_text='Standard output from process')
    stderr = models.TextField(default='', null=False, blank=True,
        help_text='Standard error from process')

    # Timing
    started_at = models.DateTimeField(default=None, null=True, blank=True,
        help_text='When process was launched')
    ended_at = models.DateTimeField(default=None, null=True, blank=True,
        help_text='When process completed/terminated')

    # Optional FKs
    binary = models.ForeignKey(
        Binary,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='process_set',
        help_text='Binary used by this process'
    )
    iface = models.ForeignKey(
        NetworkInterface,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='process_set',
        help_text='Network interface used by this process'
    )

    # Optional connection URL (for CDP, sonic, etc.)
    url = models.URLField(max_length=2048, default=None, null=True, blank=True,
        help_text='Connection URL (CDP endpoint, sonic server, etc.)')

    # Reverse relation to ArchiveResult (OneToOne from AR side)
    # archiveresult: OneToOneField defined on ArchiveResult model

    # State machine fields
    status = models.CharField(
        max_length=16,
        choices=StatusChoices.choices,
        default=StatusChoices.QUEUED,
        db_index=True
    )
    retry_at = models.DateTimeField(
        default=timezone.now,
        null=True, blank=True,
        db_index=True,
        help_text='When to retry this process'
    )

    state_machine_name: str = 'archivebox.machine.models.ProcessMachine'

    objects: ProcessManager = ProcessManager()

    class Meta:
        app_label = 'machine'
        verbose_name = 'Process'
        verbose_name_plural = 'Processes'
        indexes = [
            models.Index(fields=['machine', 'status', 'retry_at']),
            models.Index(fields=['binary', 'exit_code']),
        ]

    def __str__(self) -> str:
        cmd_str = ' '.join(self.cmd[:3]) if self.cmd else '(no cmd)'
        return f'Process[{self.id}] {cmd_str} ({self.status})'

    # Properties that delegate to related objects
    @property
    def cmd_version(self) -> str:
        """Get version from associated binary."""
        return self.binary.version if self.binary else ''

    @property
    def bin_abspath(self) -> str:
        """Get absolute path from associated binary."""
        return self.binary.abspath if self.binary else ''

    @property
    def plugin(self) -> str:
        """Get plugin name from associated ArchiveResult (if any)."""
        if hasattr(self, 'archiveresult'):
            # Inline import to avoid circular dependency
            return self.archiveresult.plugin
        return ''

    @property
    def hook_name(self) -> str:
        """Get hook name from associated ArchiveResult (if any)."""
        if hasattr(self, 'archiveresult'):
            return self.archiveresult.hook_name
        return ''

    def to_json(self) -> dict:
        """
        Convert Process model instance to a JSON-serializable dict.
        """
        from archivebox.config import VERSION
        record = {
            'type': 'Process',
            'schema_version': VERSION,
            'id': str(self.id),
            'machine_id': str(self.machine_id),
            'cmd': self.cmd,
            'pwd': self.pwd,
            'status': self.status,
            'exit_code': self.exit_code,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
        }
        # Include optional fields if set
        if self.binary_id:
            record['binary_id'] = str(self.binary_id)
        if self.pid:
            record['pid'] = self.pid
        if self.timeout:
            record['timeout'] = self.timeout
        return record

    @classmethod
    def parse_records_from_text(cls, text: str) -> list[dict]:
        """Parse JSONL records from raw text using the shared JSONL parser."""
        from archivebox.misc.jsonl import parse_line

        records: list[dict] = []
        if not text:
            return records
        for line in text.splitlines():
            record = parse_line(line)
            if record and record.get('type'):
                records.append(record)
        return records

    def get_records(self) -> list[dict]:
        """Parse JSONL records from this process's stdout."""
        stdout = self.stdout
        if not stdout and self.stdout_file and self.stdout_file.exists():
            stdout = self.stdout_file.read_text()
        return self.parse_records_from_text(stdout or '')

    @staticmethod
    def from_json(record: dict, overrides: dict = None):
        """
        Create/update Process from JSON dict.

        Args:
            record: JSON dict with 'id' or process details
            overrides: Optional dict of field overrides

        Returns:
            Process instance or None
        """
        process_id = record.get('id')
        if process_id:
            try:
                return Process.objects.get(id=process_id)
            except Process.DoesNotExist:
                pass
        return None

    def update_and_requeue(self, **kwargs):
        """
        Update process fields and requeue for worker state machine.
        Sets modified_at to ensure workers pick up changes.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.modified_at = timezone.now()
        self.save()

    # =========================================================================
    # Process.current() and hierarchy methods
    # =========================================================================

    @classmethod
    def current(cls) -> 'Process':
        """
        Get or create the Process record for the current OS process.

        Similar to Machine.current(), this:
        1. Checks cache for existing Process with matching PID
        2. Validates the cached Process is still valid (PID not reused)
        3. Creates new Process if needed

        IMPORTANT: Uses psutil to validate PID hasn't been reused.
        PIDs are recycled by OS, so we compare start times.
        """
        global _CURRENT_PROCESS

        current_pid = os.getpid()
        machine = Machine.current()

        # Check cache validity
        if _CURRENT_PROCESS:
            # Verify: same PID, same machine, cache not expired
            if (_CURRENT_PROCESS.pid == current_pid and
                _CURRENT_PROCESS.machine_id == machine.id and
                timezone.now() < _CURRENT_PROCESS.modified_at + timedelta(seconds=PROCESS_RECHECK_INTERVAL)):
                _CURRENT_PROCESS.ensure_log_files()
                return _CURRENT_PROCESS
            _CURRENT_PROCESS = None

        # Get actual process start time from OS for validation
        os_start_time = None
        if PSUTIL_AVAILABLE:
            try:
                os_proc = psutil.Process(current_pid)
                os_start_time = os_proc.create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Try to find existing Process for this PID on this machine
        # Filter by: machine + PID + RUNNING + recent + start time matches
        if os_start_time:
            existing = cls.objects.filter(
                machine=machine,
                pid=current_pid,
                status=cls.StatusChoices.RUNNING,
                started_at__gte=timezone.now() - PID_REUSE_WINDOW,
            ).order_by('-started_at').first()

            if existing and existing.started_at:
                db_start_time = existing.started_at.timestamp()
                if abs(db_start_time - os_start_time) < START_TIME_TOLERANCE:
                    _CURRENT_PROCESS = existing
                    _CURRENT_PROCESS.ensure_log_files()
                    return existing

        # No valid existing record - create new one
        parent = cls._find_parent_process(machine)
        process_type = cls._detect_process_type()

        # Use psutil cmdline if available (matches what proc() will validate against)
        # Otherwise fall back to sys.argv
        cmd = sys.argv
        if PSUTIL_AVAILABLE:
            try:
                os_proc = psutil.Process(current_pid)
                cmd = os_proc.cmdline()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Use psutil start time if available (more accurate than timezone.now())
        if os_start_time:
            started_at = datetime.fromtimestamp(os_start_time, tz=timezone.get_current_timezone())
        else:
            started_at = timezone.now()

        _CURRENT_PROCESS = cls.objects.create(
            machine=machine,
            parent=parent,
            process_type=process_type,
            cmd=cmd,
            pwd=os.getcwd(),
            pid=current_pid,
            started_at=started_at,
            status=cls.StatusChoices.RUNNING,
        )
        _CURRENT_PROCESS.ensure_log_files()
        return _CURRENT_PROCESS

    @classmethod
    def _find_parent_process(cls, machine: 'Machine' = None) -> 'Process | None':
        """
        Find the parent Process record by looking up PPID.

        IMPORTANT: Validates against PID reuse by checking:
        1. Same machine (PIDs are only unique per machine)
        2. Start time matches OS process start time
        3. Process is still RUNNING and recent

        Returns None if parent is not an ArchiveBox process.
        """
        if not PSUTIL_AVAILABLE:
            return None

        ppid = os.getppid()
        machine = machine or Machine.current()

        # Debug logging
        import sys
        # print(f"DEBUG _find_parent_process: my_pid={os.getpid()}, ppid={ppid}", file=sys.stderr)

        # Get parent process start time from OS
        try:
            os_parent = psutil.Process(ppid)
            os_parent_start = os_parent.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # print(f"DEBUG _find_parent_process: Parent process {ppid} not accessible", file=sys.stderr)
            return None  # Parent process doesn't exist

        # Find matching Process record
        candidates = cls.objects.filter(
            machine=machine,
            pid=ppid,
            status=cls.StatusChoices.RUNNING,
            started_at__gte=timezone.now() - PID_REUSE_WINDOW,
        ).order_by('-started_at')

        # print(f"DEBUG _find_parent_process: Found {candidates.count()} candidates for ppid={ppid}", file=sys.stderr)

        for candidate in candidates:
            if candidate.started_at:
                db_start_time = candidate.started_at.timestamp()
                time_diff = abs(db_start_time - os_parent_start)
                # print(f"DEBUG _find_parent_process: Checking candidate id={candidate.id} time_diff={time_diff:.2f}s tolerance={START_TIME_TOLERANCE}s", file=sys.stderr)
                if time_diff < START_TIME_TOLERANCE:
                    # print(f"DEBUG _find_parent_process: MATCH! Returning parent id={candidate.id} pid={candidate.pid}", file=sys.stderr)
                    return candidate

        # print(f"DEBUG _find_parent_process: No matching parent found for ppid={ppid}", file=sys.stderr)
        return None  # No matching ArchiveBox parent process

    @classmethod
    def _detect_process_type(cls) -> str:
        """
        Detect the type of the current process from sys.argv.
        """
        argv_str = ' '.join(sys.argv).lower()

        if 'supervisord' in argv_str:
            return cls.TypeChoices.SUPERVISORD
        elif 'orchestrator' in argv_str:
            return cls.TypeChoices.ORCHESTRATOR
        elif any(w in argv_str for w in ['crawl_worker', 'snapshot_worker', 'archiveresult_worker']):
            return cls.TypeChoices.WORKER
        elif 'archivebox' in argv_str:
            return cls.TypeChoices.CLI
        else:
            return cls.TypeChoices.BINARY

    @classmethod
    def cleanup_stale_running(cls, machine: 'Machine' = None) -> int:
        """
        Mark stale RUNNING processes as EXITED.

        Processes are stale if:
        - Status is RUNNING but OS process no longer exists
        - Status is RUNNING but started_at is older than PID_REUSE_WINDOW

        Returns count of processes cleaned up.
        """
        machine = machine or Machine.current()
        cleaned = 0

        stale = cls.objects.filter(
            machine=machine,
            status=cls.StatusChoices.RUNNING,
        )

        for proc in stale:
            is_stale = False

            # Check if too old (PID definitely reused)
            if proc.started_at and proc.started_at < timezone.now() - PID_REUSE_WINDOW:
                is_stale = True
            elif PSUTIL_AVAILABLE and proc.pid is not None:
                # Check if OS process still exists with matching start time
                try:
                    os_proc = psutil.Process(proc.pid)
                    if proc.started_at:
                        db_start = proc.started_at.timestamp()
                        os_start = os_proc.create_time()
                        if abs(db_start - os_start) > START_TIME_TOLERANCE:
                            is_stale = True  # PID reused by different process
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    is_stale = True  # Process no longer exists

            if is_stale:
                proc.status = cls.StatusChoices.EXITED
                proc.ended_at = proc.ended_at or timezone.now()
                proc.exit_code = proc.exit_code if proc.exit_code is not None else 0
                proc.save(update_fields=['status', 'ended_at', 'exit_code'])
                cleaned += 1

        return cleaned

    # =========================================================================
    # Tree traversal properties
    # =========================================================================

    @property
    def root(self) -> 'Process':
        """Get the root process (CLI command) of this hierarchy."""
        proc = self
        while proc.parent_id:
            proc = proc.parent
        return proc

    @property
    def ancestors(self) -> list['Process']:
        """Get all ancestor processes from parent to root."""
        ancestors = []
        proc = self.parent
        while proc:
            ancestors.append(proc)
            proc = proc.parent
        return ancestors

    @property
    def depth(self) -> int:
        """Get depth in the process tree (0 = root)."""
        return len(self.ancestors)

    def get_descendants(self, include_self: bool = False):
        """Get all descendant processes recursively."""
        if include_self:
            pks = [self.pk]
        else:
            pks = []

        children = list(self.children.values_list('pk', flat=True))
        while children:
            pks.extend(children)
            children = list(Process.objects.filter(parent_id__in=children).values_list('pk', flat=True))

        return Process.objects.filter(pk__in=pks)

    # =========================================================================
    # Validated psutil access via .proc property
    # =========================================================================

    @property
    def proc(self) -> 'psutil.Process | None':
        """
        Get validated psutil.Process for this record.

        Returns psutil.Process ONLY if:
        1. Process with this PID exists in OS
        2. OS process start time matches our started_at (within tolerance)
        3. Process is on current machine

        Returns None if:
        - PID doesn't exist (process exited)
        - PID was reused by a different process (start times don't match)
        - We're on a different machine than where process ran
        - psutil is not available

        This prevents accidentally matching a stale/recycled PID.
        """
        if not PSUTIL_AVAILABLE:
            return None

        # Can't get psutil.Process if we don't have a PID
        if not self.pid:
            return None

        # Can't validate processes on other machines
        if self.machine_id != Machine.current().id:
            return None

        try:
            os_proc = psutil.Process(self.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None  # Process no longer exists

        # Validate start time matches to prevent PID reuse confusion
        if self.started_at:
            os_start_time = os_proc.create_time()
            db_start_time = self.started_at.timestamp()

            if abs(os_start_time - db_start_time) > START_TIME_TOLERANCE:
                # PID has been reused by a different process!
                return None

        # Optionally validate command matches (extra safety)
        if self.cmd:
            try:
                os_cmdline = os_proc.cmdline()
                # Check if first arg (binary) matches
                if os_cmdline and self.cmd:
                    os_binary = os_cmdline[0] if os_cmdline else ''
                    db_binary = self.cmd[0] if self.cmd else ''
                    # Match by basename (handles /usr/bin/python3 vs python3)
                    if os_binary and db_binary:
                        if Path(os_binary).name != Path(db_binary).name:
                            return None  # Different binary, PID reused
            except (psutil.AccessDenied, psutil.ZombieProcess):
                pass  # Can't check cmdline, trust start time match

        return os_proc

    @property
    def is_running(self) -> bool:
        """
        Check if process is currently running via psutil.

        More reliable than checking status field since it validates
        the actual OS process exists and matches our record.
        """
        proc = self.proc
        if proc is None:
            return False
        try:
            # Treat zombies as not running (they should be reaped)
            if proc.status() == psutil.STATUS_ZOMBIE:
                return False
        except Exception:
            pass
        return proc.is_running()

    def is_alive(self) -> bool:
        """
        Alias for is_running, for compatibility with subprocess.Popen API.
        """
        return self.is_running

    def get_memory_info(self) -> dict | None:
        """Get memory usage if process is running."""
        proc = self.proc
        if proc:
            try:
                mem = proc.memory_info()
                return {'rss': mem.rss, 'vms': mem.vms}
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return None

    def get_cpu_percent(self) -> float | None:
        """Get CPU usage percentage if process is running."""
        proc = self.proc
        if proc:
            try:
                return proc.cpu_percent(interval=0.1)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return None

    def get_children_pids(self) -> list[int]:
        """Get PIDs of child processes from OS (not DB)."""
        proc = self.proc
        if proc:
            try:
                return [child.pid for child in proc.children(recursive=True)]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return []

    # =========================================================================
    # Lifecycle methods (launch, kill, poll, wait)
    # =========================================================================

    @property
    def pid_file(self) -> Path:
        """Path to PID file for this process."""
        return Path(self.pwd) / 'process.pid' if self.pwd else None

    @property
    def cmd_file(self) -> Path:
        """Path to cmd.sh script for this process."""
        return Path(self.pwd) / 'cmd.sh' if self.pwd else None

    @property
    def stdout_file(self) -> Path:
        """Path to stdout log."""
        return Path(self.pwd) / 'stdout.log' if self.pwd else None

    @property
    def stderr_file(self) -> Path:
        """Path to stderr log."""
        return Path(self.pwd) / 'stderr.log' if self.pwd else None

    def tail_stdout(self, lines: int = 50, follow: bool = False):
        """
        Tail stdout log file (like `tail` or `tail -f`).

        Args:
            lines: Number of lines to show (default 50)
            follow: If True, follow the file and yield new lines as they appear

        Yields:
            Lines from stdout
        """
        if not self.stdout_file or not self.stdout_file.exists():
            return

        if follow:
            # Follow mode - yield new lines as they appear (tail -f)
            import time
            with open(self.stdout_file, 'r') as f:
                # Seek to end minus roughly 'lines' worth of bytes
                f.seek(0, 2)  # Seek to end
                file_size = f.tell()
                # Rough estimate: 100 bytes per line
                seek_pos = max(0, file_size - (lines * 100))
                f.seek(seek_pos)

                # Skip partial line if we seeked to middle
                if seek_pos > 0:
                    f.readline()

                # Yield existing lines
                for line in f:
                    yield line.rstrip('\n')

                # Now follow for new lines
                while True:
                    line = f.readline()
                    if line:
                        yield line.rstrip('\n')
                    else:
                        time.sleep(0.1)  # Wait before checking again
        else:
            # Just get last N lines (tail -n)
            try:
                content = self.stdout_file.read_text()
                for line in content.splitlines()[-lines:]:
                    yield line
            except Exception:
                return

    def tail_stderr(self, lines: int = 50, follow: bool = False):
        """
        Tail stderr log file (like `tail` or `tail -f`).

        Args:
            lines: Number of lines to show (default 50)
            follow: If True, follow the file and yield new lines as they appear

        Yields:
            Lines from stderr
        """
        if not self.stderr_file or not self.stderr_file.exists():
            return

        if follow:
            # Follow mode - yield new lines as they appear (tail -f)
            import time
            with open(self.stderr_file, 'r') as f:
                # Seek to end minus roughly 'lines' worth of bytes
                f.seek(0, 2)  # Seek to end
                file_size = f.tell()
                # Rough estimate: 100 bytes per line
                seek_pos = max(0, file_size - (lines * 100))
                f.seek(seek_pos)

                # Skip partial line if we seeked to middle
                if seek_pos > 0:
                    f.readline()

                # Yield existing lines
                for line in f:
                    yield line.rstrip('\n')

                # Now follow for new lines
                while True:
                    line = f.readline()
                    if line:
                        yield line.rstrip('\n')
                    else:
                        time.sleep(0.1)  # Wait before checking again
        else:
            # Just get last N lines (tail -n)
            try:
                content = self.stderr_file.read_text()
                for line in content.splitlines()[-lines:]:
                    yield line
            except Exception:
                return

    def pipe_stdout(self, lines: int = 10, follow: bool = True):
        """
        Pipe stdout to sys.stdout.

        Args:
            lines: Number of initial lines to show
            follow: If True, follow the file and print new lines as they appear
        """
        import sys
        for line in self.tail_stdout(lines=lines, follow=follow):
            print(line, file=sys.stdout, flush=True)

    def pipe_stderr(self, lines: int = 10, follow: bool = True):
        """
        Pipe stderr to sys.stderr.

        Args:
            lines: Number of initial lines to show
            follow: If True, follow the file and print new lines as they appear
        """
        import sys
        for line in self.tail_stderr(lines=lines, follow=follow):
            print(line, file=sys.stderr, flush=True)

    def _write_pid_file(self) -> None:
        """Write PID file with mtime set to process start time."""
        if self.pid and self.started_at and self.pid_file:
            # Write PID to file
            self.pid_file.write_text(str(self.pid))
            # Set mtime to process start time for validation
            try:
                start_time = self.started_at.timestamp()
                os.utime(self.pid_file, (start_time, start_time))
            except OSError:
                pass  # mtime optional, validation degrades gracefully

    def _write_cmd_file(self) -> None:
        """Write cmd.sh script for debugging/validation."""
        if self.cmd and self.cmd_file:
            # Escape shell arguments (quote if contains space, ", or $)
            def escape(arg: str) -> str:
                return f'"{arg.replace(chr(34), chr(92)+chr(34))}"' if any(c in arg for c in ' "$') else arg

            # Write executable shell script
            script = '#!/bin/bash\n' + ' '.join(escape(arg) for arg in self.cmd) + '\n'
            self.cmd_file.write_text(script)
            try:
                self.cmd_file.chmod(0o755)
            except OSError:
                pass

    def ensure_log_files(self) -> None:
        """Ensure stdout/stderr log files exist for this process."""
        if not self.pwd:
            return
        try:
            Path(self.pwd).mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        try:
            if self.stdout_file:
                self.stdout_file.touch(exist_ok=True)
            if self.stderr_file:
                self.stderr_file.touch(exist_ok=True)
        except OSError:
            return

    def _build_env(self) -> dict:
        """Build environment dict for subprocess, merging stored env with system."""
        import json

        env = os.environ.copy()

        # Convert all values to strings for subprocess.Popen
        if self.env:
            for key, value in self.env.items():
                if value is None:
                    continue
                elif isinstance(value, str):
                    env[key] = value  # Already a string, use as-is
                elif isinstance(value, bool):
                    env[key] = 'True' if value else 'False'
                elif isinstance(value, (int, float)):
                    env[key] = str(value)
                else:
                    # Lists, dicts, etc. - serialize to JSON
                    env[key] = json.dumps(value, default=str)

        return env

    def launch(self, background: bool = False, cwd: str | None = None) -> 'Process':
        """
        Spawn the subprocess and update this Process record.

        Args:
            background: If True, don't wait for completion (for daemons/bg hooks)
            cwd: Working directory for the subprocess (defaults to self.pwd)

        Returns:
            self (updated with pid, started_at, etc.)
        """
        import subprocess
        import time

        # Validate pwd is set (required for output files)
        if not self.pwd:
            raise ValueError("Process.pwd must be set before calling launch()")

        # Use provided cwd or default to pwd
        working_dir = cwd or self.pwd

        # Ensure output directory exists
        Path(self.pwd).mkdir(parents=True, exist_ok=True)

        # Write cmd.sh for debugging
        self._write_cmd_file()

        stdout_path = self.stdout_file
        stderr_path = self.stderr_file

        with open(stdout_path, 'a') as out, open(stderr_path, 'a') as err:
            proc = subprocess.Popen(
                self.cmd,
                cwd=working_dir,
                stdout=out,
                stderr=err,
                env=self._build_env(),
            )

            # Get accurate start time from psutil if available
            if PSUTIL_AVAILABLE:
                try:
                    ps_proc = psutil.Process(proc.pid)
                    self.started_at = datetime.fromtimestamp(
                        ps_proc.create_time(),
                        tz=timezone.get_current_timezone()
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    self.started_at = timezone.now()
            else:
                self.started_at = timezone.now()

            self.pid = proc.pid
            self.status = self.StatusChoices.RUNNING
            self.save()

            self._write_pid_file()

            if not background:
                try:
                    proc.wait(timeout=self.timeout)
                    self.exit_code = proc.returncode
                except subprocess.TimeoutExpired:
                    import signal

                    proc.kill()
                    proc.wait()
                    self.exit_code = 128 + signal.SIGKILL

                self.ended_at = timezone.now()
                if stdout_path.exists():
                    self.stdout = stdout_path.read_text()
                if stderr_path.exists():
                    self.stderr = stderr_path.read_text()
                self.status = self.StatusChoices.EXITED
                self.save()

        return self

    def kill(self, signal_num: int = 15) -> bool:
        """
        Kill this process and update status.

        Uses self.proc for safe killing - only kills if PID matches
        our recorded process (prevents killing recycled PIDs).

        Args:
            signal_num: Signal to send (default SIGTERM=15)

        Returns:
            True if killed successfully, False otherwise
        """
        # Use validated psutil.Process to ensure we're killing the right process
        proc = self.proc
        if proc is None:
            # Process doesn't exist or PID was recycled - just update status
            if self.status != self.StatusChoices.EXITED:
                self.status = self.StatusChoices.EXITED
                self.ended_at = self.ended_at or timezone.now()
                self.save()
            return False

        try:
            # Safe to kill - we validated it's our process via start time match
            proc.send_signal(signal_num)

            # Update our record
            # Use standard Unix convention: 128 + signal number
            self.exit_code = 128 + signal_num
            self.ended_at = timezone.now()
            self.status = self.StatusChoices.EXITED
            self.save()

            # Clean up PID file
            if self.pid_file and self.pid_file.exists():
                self.pid_file.unlink(missing_ok=True)

            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            # Process already exited between proc check and kill
            self.status = self.StatusChoices.EXITED
            self.ended_at = self.ended_at or timezone.now()
            self.save()
            return False

    def poll(self) -> int | None:
        """
        Check if process has exited and update status if so.

        Cleanup when process exits:
        - Copy stdout/stderr to DB (keep files for debugging)
        - Delete PID file

        Returns:
            exit_code if exited, None if still running
        """
        if self.status == self.StatusChoices.EXITED:
            if self.exit_code == -1:
                self.exit_code = 137
                self.save(update_fields=['exit_code'])
            return self.exit_code

        if not self.is_running:
            # Reap child process if it's a zombie (best-effort)
            proc = self.proc
            if proc is not None:
                try:
                    proc.wait(timeout=0)
                except Exception:
                    pass
            # Process exited - read output and copy to DB
            if self.stdout_file and self.stdout_file.exists():
                self.stdout = self.stdout_file.read_text()
                # TODO: Uncomment to cleanup (keeping for debugging for now)
                # self.stdout_file.unlink(missing_ok=True)
            if self.stderr_file and self.stderr_file.exists():
                self.stderr = self.stderr_file.read_text()
                # TODO: Uncomment to cleanup (keeping for debugging for now)
                # self.stderr_file.unlink(missing_ok=True)

            # Clean up PID file (not needed for debugging)
            if self.pid_file and self.pid_file.exists():
                self.pid_file.unlink(missing_ok=True)

            # TODO: Uncomment to cleanup cmd.sh (keeping for debugging for now)
            # if self.pwd:
            #     cmd_file = Path(self.pwd) / 'cmd.sh'
            #     if cmd_file.exists():
            #         cmd_file.unlink(missing_ok=True)

            # Try to get exit code from proc or default to unknown
            self.exit_code = self.exit_code if self.exit_code is not None else 0
            if self.exit_code == -1:
                self.exit_code = 137
            self.ended_at = timezone.now()
            self.status = self.StatusChoices.EXITED
            self.save()
            return self.exit_code

        return None  # Still running

    def wait(self, timeout: int | None = None) -> int:
        """
        Wait for process to exit, polling periodically.

        Args:
            timeout: Max seconds to wait (None = use self.timeout)

        Returns:
            exit_code

        Raises:
            TimeoutError if process doesn't exit in time
        """
        import time

        timeout = timeout or self.timeout
        start = time.time()

        while True:
            exit_code = self.poll()
            if exit_code is not None:
                return exit_code

            if time.time() - start > timeout:
                raise TimeoutError(f"Process {self.id} did not exit within {timeout}s")

            time.sleep(0.1)

    def terminate(self, graceful_timeout: float = 5.0) -> bool:
        """
        Gracefully terminate process: SIGTERM → wait → SIGKILL.

        This consolidates the scattered SIGTERM/SIGKILL logic from:
        - crawls/models.py Crawl.cleanup()
        - workers/pid_utils.py stop_worker()
        - supervisord_util.py stop_existing_supervisord_process()

        Args:
            graceful_timeout: Seconds to wait after SIGTERM before SIGKILL

        Returns:
            True if process was terminated, False if already dead
        """
        import time
        import signal

        proc = self.proc
        if proc is None:
            # Already dead - just update status
            if self.status != self.StatusChoices.EXITED:
                self.status = self.StatusChoices.EXITED
                self.ended_at = self.ended_at or timezone.now()
                self.save()
            return False

        try:
            # Step 1: Send SIGTERM for graceful shutdown
            proc.terminate()

            # Step 2: Wait for graceful exit
            try:
                exit_status = proc.wait(timeout=graceful_timeout)
                # Process exited gracefully
                # psutil.Process.wait() returns the exit status
                self.exit_code = exit_status if exit_status is not None else 0
                self.status = self.StatusChoices.EXITED
                self.ended_at = timezone.now()
                self.save()
                return True
            except psutil.TimeoutExpired:
                pass  # Still running, need to force kill

            # Step 3: Force kill with SIGKILL
            proc.kill()
            proc.wait(timeout=2)

            # Use standard Unix convention: 128 + signal number
            self.exit_code = 128 + signal.SIGKILL
            self.status = self.StatusChoices.EXITED
            self.ended_at = timezone.now()
            self.save()
            return True

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Process already dead
            self.status = self.StatusChoices.EXITED
            self.ended_at = self.ended_at or timezone.now()
            self.save()
            return False

    def kill_tree(self, graceful_timeout: float = 2.0) -> int:
        """
        Kill this process and all its children (OS children, not DB children) in parallel.

        Uses parallel polling approach - sends SIGTERM to all processes at once,
        then polls all simultaneously with individual deadline tracking.

        This consolidates the scattered child-killing logic from:
        - crawls/models.py Crawl.cleanup() os.killpg()
        - supervisord_util.py stop_existing_supervisord_process()

        Args:
            graceful_timeout: Seconds to wait after SIGTERM before SIGKILL

        Returns:
            Number of processes killed (including self)
        """
        import signal
        import time
        import os

        killed_count = 0
        used_sigkill = False
        proc = self.proc
        if proc is None:
            # Already dead
            if self.status != self.StatusChoices.EXITED:
                self.status = self.StatusChoices.EXITED
                self.ended_at = self.ended_at or timezone.now()
                self.save()
            return 0

        try:
            # Phase 1: Get all children and send SIGTERM to entire tree in parallel
            children = proc.children(recursive=True)
            deadline = time.time() + graceful_timeout

            # Send SIGTERM to all children first (non-blocking)
            for child in children:
                try:
                    os.kill(child.pid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass

            # Send SIGTERM to parent
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

            # Phase 2: Poll all processes in parallel
            all_procs = children + [proc]
            still_running = set(p.pid for p in all_procs)

            while still_running and time.time() < deadline:
                time.sleep(0.1)

                for pid in list(still_running):
                    try:
                        # Check if process exited
                        os.kill(pid, 0)  # Signal 0 checks if process exists
                    except (OSError, ProcessLookupError):
                        # Process exited
                        still_running.remove(pid)
                        killed_count += 1

            # Phase 3: SIGKILL any stragglers that exceeded timeout
            if still_running:
                for pid in still_running:
                    try:
                        os.kill(pid, signal.SIGKILL)
                        killed_count += 1
                        used_sigkill = True
                    except (OSError, ProcessLookupError):
                        pass

            # Update self status
            if used_sigkill:
                self.exit_code = 128 + signal.SIGKILL
            else:
                self.exit_code = 128 + signal.SIGTERM if killed_count > 0 else 0
            self.status = self.StatusChoices.EXITED
            self.ended_at = timezone.now()
            self.save()

            return killed_count

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Process tree already dead
            self.status = self.StatusChoices.EXITED
            self.ended_at = self.ended_at or timezone.now()
            self.save()
            return killed_count

    def kill_children_db(self) -> int:
        """
        Kill all DB-tracked child processes (via parent FK).

        Different from kill_tree() which uses OS children.
        This kills processes created via Process.create(parent=self).

        Returns:
            Number of child Process records killed
        """
        killed = 0
        for child in self.children.filter(status=self.StatusChoices.RUNNING):
            if child.terminate():
                killed += 1
        return killed

    # =========================================================================
    # Class methods for querying processes
    # =========================================================================

    @classmethod
    def get_running(cls, process_type: str = None, machine: 'Machine' = None) -> 'QuerySet[Process]':
        """
        Get all running processes, optionally filtered by type.

        Replaces:
        - workers/pid_utils.py get_all_worker_pids()
        - workers/orchestrator.py get_total_worker_count()

        Args:
            process_type: Filter by TypeChoices (e.g., 'worker', 'hook')
            machine: Filter by machine (defaults to current)

        Returns:
            QuerySet of running Process records
        """
        machine = machine or Machine.current()
        qs = cls.objects.filter(
            machine=machine,
            status=cls.StatusChoices.RUNNING,
        )
        if process_type:
            qs = qs.filter(process_type=process_type)
        return qs

    @classmethod
    def get_running_count(cls, process_type: str = None, machine: 'Machine' = None) -> int:
        """
        Get count of running processes.

        Replaces:
        - workers/pid_utils.py get_running_worker_count()
        """
        return cls.get_running(process_type=process_type, machine=machine).count()

    @classmethod
    def stop_all(cls, process_type: str = None, machine: 'Machine' = None, graceful: bool = True) -> int:
        """
        Stop all running processes of a given type.

        Args:
            process_type: Filter by TypeChoices
            machine: Filter by machine
            graceful: If True, use terminate() (SIGTERM→SIGKILL), else kill()

        Returns:
            Number of processes stopped
        """
        stopped = 0
        for proc in cls.get_running(process_type=process_type, machine=machine):
            if graceful:
                if proc.terminate():
                    stopped += 1
            else:
                if proc.kill():
                    stopped += 1
        return stopped

    @classmethod
    def get_next_worker_id(cls, process_type: str = 'worker', machine: 'Machine' = None) -> int:
        """
        Get the next available worker ID for spawning new workers.

        Replaces workers/pid_utils.py get_next_worker_id().
        Simply returns count of running workers of this type.

        Args:
            process_type: Worker type to count
            machine: Machine to scope query

        Returns:
            Next available worker ID (0-indexed)
        """
        return cls.get_running_count(process_type=process_type, machine=machine)

    @classmethod
    def cleanup_orphaned_chrome(cls) -> int:
        """
        Kill orphaned Chrome processes using chrome_utils.js killZombieChrome.

        Scans DATA_DIR for chrome/*.pid files from stale crawls (>5 min old)
        and kills any orphaned Chrome processes.

        Called by:
        - Orchestrator on startup (cleanup from previous crashes)
        - Orchestrator periodically (every N minutes)

        Returns:
            Number of zombie Chrome processes killed
        """
        import subprocess
        from pathlib import Path
        from django.conf import settings

        chrome_utils = Path(__file__).parent.parent / 'plugins' / 'chrome' / 'chrome_utils.js'
        if not chrome_utils.exists():
            return 0

        try:
            result = subprocess.run(
                ['node', str(chrome_utils), 'killZombieChrome', str(settings.DATA_DIR)],
                capture_output=True,
                timeout=30,
                text=True,
            )
            if result.returncode == 0:
                killed = int(result.stdout.strip())
                if killed > 0:
                    print(f'[yellow]🧹 Cleaned up {killed} orphaned Chrome processes[/yellow]')
                return killed
        except (subprocess.TimeoutExpired, ValueError, FileNotFoundError) as e:
            print(f'[red]Failed to cleanup orphaned Chrome: {e}[/red]')

        return 0

    @classmethod
    def cleanup_orphaned_workers(cls) -> int:
        """
        Kill orphaned worker/hook processes whose root process is no longer running.

        Orphaned if:
        - Root (orchestrator/cli) is not running, or
        - No orchestrator/cli ancestor exists.

        Standalone worker runs (archivebox run --snapshot-id) are allowed.
        """
        killed = 0

        running_children = cls.objects.filter(
            process_type__in=[cls.TypeChoices.WORKER, cls.TypeChoices.HOOK],
            status=cls.StatusChoices.RUNNING,
        )

        for proc in running_children:
            if not proc.is_running:
                continue

            root = proc.root
            # Standalone worker/hook process (run directly)
            if root.id == proc.id and root.process_type in (cls.TypeChoices.WORKER, cls.TypeChoices.HOOK):
                continue

            # If root is an active orchestrator/cli, keep it
            if root.process_type in (cls.TypeChoices.ORCHESTRATOR, cls.TypeChoices.CLI) and root.is_running:
                continue

            try:
                if proc.process_type == cls.TypeChoices.HOOK:
                    proc.kill_tree(graceful_timeout=1.0)
                else:
                    proc.terminate(graceful_timeout=1.0)
                killed += 1
            except Exception:
                continue

        if killed:
            print(f'[yellow]🧹 Cleaned up {killed} orphaned worker/hook process(es)[/yellow]')
        return killed


# =============================================================================
# Binary State Machine
# =============================================================================

class BinaryMachine(BaseStateMachine, strict_states=True):
    """
    State machine for managing Binary installation lifecycle.

    Simple 2-state machine:
    ┌─────────────────────────────────────────────────────────────┐
    │ QUEUED State                                                │
    │  • Binary needs to be installed                             │
    └─────────────────────────────────────────────────────────────┘
                            ↓ tick() when can_install()
                            ↓ Synchronous installation during transition
    ┌─────────────────────────────────────────────────────────────┐
    │ INSTALLED State                                             │
    │  • Binary installed (abspath, version, sha256 set)          │
    │  • Health stats incremented                                 │
    └─────────────────────────────────────────────────────────────┘

    If installation fails, Binary stays in QUEUED with retry_at bumped.
    """

    model_attr_name = 'binary'

    # States
    queued = State(value=Binary.StatusChoices.QUEUED, initial=True)
    installed = State(value=Binary.StatusChoices.INSTALLED, final=True)

    # Tick Event - install happens during transition
    tick = (
        queued.to.itself(unless='can_install') |
        queued.to(installed, cond='can_install', on='on_install')
    )

    def can_install(self) -> bool:
        """Check if binary installation can start."""
        return bool(self.binary.name and self.binary.binproviders)

    @queued.enter
    def enter_queued(self):
        """Binary is queued for installation."""
        self.binary.update_and_requeue(
            retry_at=timezone.now(),
            status=Binary.StatusChoices.QUEUED,
        )

    def on_install(self):
        """Called during queued→installed transition. Runs installation synchronously."""
        import sys

        print(f'[cyan]      🔄 BinaryMachine.on_install() - installing {self.binary.name}[/cyan]', file=sys.stderr)

        # Run installation hooks (synchronous, updates abspath/version/sha256 and sets status)
        self.binary.run()

        # Check if installation succeeded by looking at updated status
        # Note: Binary.run() updates self.binary.status internally but doesn't refresh our reference
        self.binary.refresh_from_db()

        if self.binary.status != Binary.StatusChoices.INSTALLED:
            # Installation failed - abort transition, stay in queued
            print(f'[red]      ❌ BinaryMachine - {self.binary.name} installation failed, retrying later[/red]', file=sys.stderr)

            # Bump retry_at to try again later
            self.binary.update_and_requeue(
                retry_at=timezone.now() + timedelta(seconds=300),  # Retry in 5 minutes
                status=Binary.StatusChoices.QUEUED,  # Ensure we stay queued
            )

            # Increment health stats for failure
            self.binary.increment_health_stats(success=False)

            # Abort the transition - this will raise an exception and keep us in queued
            raise Exception(f'Binary {self.binary.name} installation failed')

        print(f'[cyan]      ✅ BinaryMachine - {self.binary.name} installed successfully[/cyan]', file=sys.stderr)

    @installed.enter
    def enter_installed(self):
        """Binary installed successfully."""
        self.binary.update_and_requeue(
            retry_at=None,
            status=Binary.StatusChoices.INSTALLED,
        )

        # Increment health stats
        self.binary.increment_health_stats(success=True)


# =============================================================================
# Process State Machine
# =============================================================================

class ProcessMachine(BaseStateMachine, strict_states=True):
    """
    State machine for managing Process (OS subprocess) lifecycle.

    Process Lifecycle:
    ┌─────────────────────────────────────────────────────────────┐
    │ QUEUED State                                                │
    │  • Process ready to launch, waiting for resources           │
    └─────────────────────────────────────────────────────────────┘
                            ↓ tick() when can_start()
    ┌─────────────────────────────────────────────────────────────┐
    │ RUNNING State → enter_running()                             │
    │  1. process.launch()                                        │
    │     • Spawn subprocess with cmd, pwd, env, timeout          │
    │     • Set pid, started_at                                   │
    │     • Process runs in background or foreground              │
    │  2. Monitor process completion                              │
    │     • Check exit code when process completes                │
    └─────────────────────────────────────────────────────────────┘
                            ↓ tick() checks is_exited()
    ┌─────────────────────────────────────────────────────────────┐
    │ EXITED State                                                │
    │  • Process completed (exit_code set)                        │
    │  • Health stats incremented                                 │
    │  • stdout/stderr captured                                   │
    └─────────────────────────────────────────────────────────────┘

    Note: This is a simpler state machine than ArchiveResult.
    Process is just about execution lifecycle. ArchiveResult handles
    the archival-specific logic (status, output parsing, etc.).
    """

    model_attr_name = 'process'

    # States
    queued = State(value=Process.StatusChoices.QUEUED, initial=True)
    running = State(value=Process.StatusChoices.RUNNING)
    exited = State(value=Process.StatusChoices.EXITED, final=True)

    # Tick Event - transitions based on conditions
    tick = (
        queued.to.itself(unless='can_start') |
        queued.to(running, cond='can_start') |
        running.to.itself(unless='is_exited') |
        running.to(exited, cond='is_exited')
    )

    # Additional events (for explicit control)
    launch = queued.to(running)
    kill = running.to(exited)

    def can_start(self) -> bool:
        """Check if process can start (has cmd and machine)."""
        return bool(self.process.cmd and self.process.machine)

    def is_exited(self) -> bool:
        """Check if process has exited (exit_code is set)."""
        return self.process.exit_code is not None

    @queued.enter
    def enter_queued(self):
        """Process is queued for execution."""
        self.process.update_and_requeue(
            retry_at=timezone.now(),
            status=Process.StatusChoices.QUEUED,
        )

    @running.enter
    def enter_running(self):
        """Start process execution."""
        # Lock the process while it runs
        self.process.update_and_requeue(
            retry_at=timezone.now() + timedelta(seconds=self.process.timeout),
            status=Process.StatusChoices.RUNNING,
            started_at=timezone.now(),
        )

        # Launch the subprocess
        # NOTE: This is a placeholder - actual launch logic would
        # be implemented based on how hooks currently spawn processes
        # For now, Process is a data model that tracks execution metadata
        # The actual subprocess spawning is still handled by run_hook()

        # Mark as immediately exited for now (until we refactor run_hook)
        # In the future, this would actually spawn the subprocess
        self.process.exit_code = 0  # Placeholder
        self.process.save()

    @exited.enter
    def enter_exited(self):
        """Process has exited."""
        self.process.update_and_requeue(
            retry_at=None,
            status=Process.StatusChoices.EXITED,
            ended_at=timezone.now(),
        )


# =============================================================================
# State Machine Registration
# =============================================================================

# Manually register state machines with python-statemachine registry
registry.register(BinaryMachine)
registry.register(ProcessMachine)
