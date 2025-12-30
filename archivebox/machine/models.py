__package__ = 'archivebox.machine'

import socket
from archivebox.uuid_compat import uuid7
from datetime import timedelta

from statemachine import State, registry

from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property

from archivebox.base_models.models import ModelWithHealthStats
from archivebox.workers.models import BaseStateMachine
from .detect import get_host_guid, get_os_info, get_vm_info, get_host_network, get_host_stats

_CURRENT_MACHINE = None
_CURRENT_INTERFACE = None
_CURRENT_BINARIES = {}

MACHINE_RECHECK_INTERVAL = 7 * 24 * 60 * 60
NETWORK_INTERFACE_RECHECK_INTERVAL = 1 * 60 * 60
BINARY_RECHECK_INTERVAL = 1 * 30 * 60


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

    @staticmethod
    def from_jsonl(record: dict, overrides: dict = None):
        """
        Update Machine config from JSONL record.

        Args:
            record: JSONL record with '_method': 'update', 'key': '...', 'value': '...'
            overrides: Not used

        Returns:
            Machine instance or None
        """
        method = record.get('_method')
        if method == 'update':
            key = record.get('key')
            value = record.get('value')
            if key and value:
                machine = Machine.current()
                if not machine.config:
                    machine.config = {}
                machine.config[key] = value
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
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)

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


class Binary(ModelWithHealthStats):
    """
    Tracks an binary on a specific machine.

    Follows the unified state machine pattern:
    - queued: Binary needs to be installed
    - started: Installation in progress
    - succeeded: Binary installed successfully (abspath, version, sha256 populated)
    - failed: Installation failed

    State machine calls run() which executes on_Binary__install_* hooks
    to install the binary using the specified providers.
    """

    class StatusChoices(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        STARTED = 'started', 'Started'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'

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
    status = models.CharField(max_length=16, choices=StatusChoices.choices, default=StatusChoices.QUEUED, db_index=True)
    retry_at = models.DateTimeField(default=timezone.now, null=True, blank=True, db_index=True,
        help_text="When to retry this binary installation")
    output_dir = models.CharField(max_length=255, default='', null=False, blank=True,
        help_text="Directory where installation hook logs are stored")

    # Health stats
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)

    state_machine_name: str = 'archivebox.machine.models.BinaryMachine'

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

    def to_jsonl(self) -> dict:
        """
        Convert Binary model instance to a JSONL record.
        """
        return {
            'type': 'Binary',
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
    def from_jsonl(record: dict, overrides: dict = None):
        """
        Create/update Binary from JSONL record.

        Handles two cases:
        1. From binaries.jsonl: creates queued binary with name, binproviders, overrides
        2. From hook output: updates binary with abspath, version, sha256, binprovider

        Args:
            record: JSONL record with 'name' and either:
                    - 'binproviders', 'overrides' (from binaries.jsonl)
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

        # Case 1: From binaries.jsonl - create queued binary
        if 'binproviders' in record or ('overrides' in record and not record.get('abspath')):
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

        # Case 2: From hook output - update with installation results
        abspath = record.get('abspath')
        version = record.get('version')
        if not abspath or not version:
            return None

        binary, _ = Binary.objects.update_or_create(
            machine=machine,
            name=name,
            defaults={
                'abspath': abspath,
                'version': version,
                'sha256': record.get('sha256', ''),
                'binprovider': record.get('binprovider', 'env'),
                'status': Binary.StatusChoices.SUCCEEDED,
                'retry_at': None,
            }
        )
        return binary

    @property
    def OUTPUT_DIR(self):
        """Return the output directory for this binary installation."""
        from pathlib import Path
        from django.conf import settings

        DATA_DIR = getattr(settings, 'DATA_DIR', Path.cwd())
        return Path(DATA_DIR) / 'machines' / str(self.machine_id) / 'binaries' / self.name / str(self.id)

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
        config = get_config(scope='global')

        # Create output directory
        output_dir = self.OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = str(output_dir)
        self.save()

        # Discover ALL on_Binary__install_* hooks
        hooks = discover_hooks('Binary', config=config)
        if not hooks:
            self.status = self.StatusChoices.FAILED
            self.save()
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
            result = run_hook(
                hook,
                output_dir=plugin_output_dir,
                config=config,
                timeout=600,  # 10 min timeout for binary installation
                **hook_kwargs
            )

            # Background hook (unlikely for binary installation, but handle it)
            if result is None:
                continue

            # Failed or skipped hook - try next one
            if result['returncode'] != 0:
                continue

            # Parse JSONL output to check for successful installation
            stdout_file = plugin_output_dir / 'stdout.log'
            if stdout_file.exists():
                stdout = stdout_file.read_text()
                for line in stdout.splitlines():
                    if line.strip() and line.strip().startswith('{'):
                        try:
                            record = json.loads(line)
                            if record.get('type') == 'Binary' and record.get('abspath'):
                                # Update self from successful installation
                                self.abspath = record['abspath']
                                self.version = record.get('version', '')
                                self.sha256 = record.get('sha256', '')
                                self.binprovider = record.get('binprovider', 'env')
                                self.status = self.StatusChoices.SUCCEEDED
                                self.save()
                                return
                        except json.JSONDecodeError:
                            continue

        # No hook succeeded
        self.status = self.StatusChoices.FAILED
        self.save()

    def cleanup(self):
        """
        Clean up background binary installation hooks.

        Called by state machine if needed (not typically used for binaries
        since installations are foreground, but included for consistency).
        """
        from pathlib import Path
        from archivebox.hooks import kill_process

        output_dir = self.OUTPUT_DIR
        if not output_dir.exists():
            return

        # Kill any background hooks
        for plugin_dir in output_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            pid_file = plugin_dir / 'hook.pid'
            if pid_file.exists():
                kill_process(pid_file)


# =============================================================================
# Process Model
# =============================================================================

class ProcessManager(models.Manager):
    """Manager for Process model."""

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


class Process(ModelWithHealthStats):
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

    # Primary fields
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    # Machine FK - required (every process runs on a machine)
    machine = models.ForeignKey(
        Machine,
        on_delete=models.CASCADE,
        null=False,
        related_name='processes',
        help_text='Machine where this process executed'
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
        related_name='processes',
        help_text='Binary used by this process'
    )
    iface = models.ForeignKey(
        NetworkInterface,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='processes',
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

    # Health stats
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)

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

    def to_jsonl(self) -> dict:
        """
        Convert Process model instance to a JSONL record.
        """
        record = {
            'type': 'Process',
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

    def update_and_requeue(self, **kwargs):
        """
        Update process fields and requeue for worker state machine.
        Sets modified_at to ensure workers pick up changes.
        """
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.modified_at = timezone.now()
        self.save()


# =============================================================================
# Binary State Machine
# =============================================================================

class BinaryMachine(BaseStateMachine, strict_states=True):
    """
    State machine for managing Binary installation lifecycle.

    Hook Lifecycle:
    ┌─────────────────────────────────────────────────────────────┐
    │ QUEUED State                                                │
    │  • Binary needs to be installed                             │
    └─────────────────────────────────────────────────────────────┘
                            ↓ tick() when can_start()
    ┌─────────────────────────────────────────────────────────────┐
    │ STARTED State → enter_started()                             │
    │  1. binary.run()                                            │
    │     • discover_hooks('Binary') → all on_Binary__install_*   │
    │     • Try each provider hook in sequence:                   │
    │       - run_hook(script, output_dir, ...)                   │
    │       - If returncode == 0:                                 │
    │         * Read stdout.log                                   │
    │         * Parse JSONL for 'Binary' record with abspath      │
    │         * Update self: abspath, version, sha256, provider   │
    │         * Set status=SUCCEEDED, RETURN                      │
    │     • If no hook succeeds: set status=FAILED                │
    └─────────────────────────────────────────────────────────────┘
                            ↓ tick() checks status
    ┌─────────────────────────────────────────────────────────────┐
    │ SUCCEEDED / FAILED                                          │
    │  • Set by binary.run() based on hook results                │
    │  • Health stats incremented (num_uses_succeeded/failed)     │
    └─────────────────────────────────────────────────────────────┘
    """

    model_attr_name = 'binary'

    # States
    queued = State(value=Binary.StatusChoices.QUEUED, initial=True)
    started = State(value=Binary.StatusChoices.STARTED)
    succeeded = State(value=Binary.StatusChoices.SUCCEEDED, final=True)
    failed = State(value=Binary.StatusChoices.FAILED, final=True)

    # Tick Event - transitions based on conditions
    tick = (
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to.itself(unless='is_finished') |
        started.to(succeeded, cond='is_succeeded') |
        started.to(failed, cond='is_failed')
    )

    def can_start(self) -> bool:
        """Check if binary installation can start."""
        return bool(self.binary.name and self.binary.binproviders)

    def is_succeeded(self) -> bool:
        """Check if installation succeeded (status was set by run())."""
        return self.binary.status == Binary.StatusChoices.SUCCEEDED

    def is_failed(self) -> bool:
        """Check if installation failed (status was set by run())."""
        return self.binary.status == Binary.StatusChoices.FAILED

    def is_finished(self) -> bool:
        """Check if installation has completed (success or failure)."""
        return self.binary.status in (
            Binary.StatusChoices.SUCCEEDED,
            Binary.StatusChoices.FAILED,
        )

    @queued.enter
    def enter_queued(self):
        """Binary is queued for installation."""
        self.binary.update_and_requeue(
            retry_at=timezone.now(),
            status=Binary.StatusChoices.QUEUED,
        )

    @started.enter
    def enter_started(self):
        """Start binary installation."""
        # Lock the binary while installation runs
        self.binary.update_and_requeue(
            retry_at=timezone.now() + timedelta(seconds=300),  # 5 min timeout for installation
            status=Binary.StatusChoices.STARTED,
        )

        # Run installation hooks
        self.binary.run()

        # Save updated status (run() updates status to succeeded/failed)
        self.binary.save()

    @succeeded.enter
    def enter_succeeded(self):
        """Binary installed successfully."""
        self.binary.update_and_requeue(
            retry_at=None,
            status=Binary.StatusChoices.SUCCEEDED,
        )

        # Increment health stats
        self.binary.increment_health_stats(success=True)

    @failed.enter
    def enter_failed(self):
        """Binary installation failed."""
        self.binary.update_and_requeue(
            retry_at=None,
            status=Binary.StatusChoices.FAILED,
        )

        # Increment health stats
        self.binary.increment_health_stats(success=False)


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
        success = self.process.exit_code == 0

        self.process.update_and_requeue(
            retry_at=None,
            status=Process.StatusChoices.EXITED,
            ended_at=timezone.now(),
        )

        # Increment health stats based on exit code
        self.process.increment_health_stats(success=success)


# =============================================================================
# State Machine Registration
# =============================================================================

# Manually register state machines with python-statemachine registry
registry.register(BinaryMachine)
registry.register(ProcessMachine)


