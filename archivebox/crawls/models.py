__package__ = 'archivebox.crawls'

from typing import TYPE_CHECKING, Iterable
from datetime import timedelta
from archivebox.uuid_compat import uuid7
from pathlib import Path

from django.db import models
from django.db.models import QuerySet
from django.core.validators import MaxValueValidator, MinValueValidator
from django.conf import settings
from django.urls import reverse_lazy
from django.utils import timezone
from django_stubs_ext.db.models import TypedModelMeta
from statemachine import State, registry
from rich import print

from archivebox.config import CONSTANTS
from archivebox.base_models.models import ModelWithSerializers, ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats, get_or_create_system_user_pk
from archivebox.workers.models import ModelWithStateMachine, BaseStateMachine

if TYPE_CHECKING:
    from archivebox.core.models import Snapshot, ArchiveResult


class CrawlSchedule(ModelWithSerializers, ModelWithNotes, ModelWithHealthStats):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    modified_at = models.DateTimeField(auto_now=True)

    template: 'Crawl' = models.ForeignKey('Crawl', on_delete=models.CASCADE, null=False, blank=False)  # type: ignore
    schedule = models.CharField(max_length=64, blank=False, null=False)
    is_enabled = models.BooleanField(default=True)
    label = models.CharField(max_length=64, blank=True, null=False, default='')
    notes = models.TextField(blank=True, null=False, default='')

    crawl_set: models.Manager['Crawl']

    class Meta(TypedModelMeta):
        app_label = 'crawls'
        verbose_name = 'Scheduled Crawl'
        verbose_name_plural = 'Scheduled Crawls'

    def __str__(self) -> str:
        urls_preview = self.template.urls[:64] if self.template and self.template.urls else ""
        return f'[{self.id}] {urls_preview} @ {self.schedule}'

    @property
    def api_url(self) -> str:
        return reverse_lazy('api-1:get_any', args=[self.id])

    def save(self, *args, **kwargs):
        self.label = self.label or (self.template.label if self.template else '')
        super().save(*args, **kwargs)
        if self.template:
            self.template.schedule = self
            self.template.save()


class Crawl(ModelWithOutputDir, ModelWithConfig, ModelWithHealthStats, ModelWithStateMachine):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    modified_at = models.DateTimeField(auto_now=True)

    urls = models.TextField(blank=False, null=False, help_text='Newline-separated list of URLs to crawl')
    config = models.JSONField(default=dict, null=True, blank=True)
    max_depth = models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(4)])
    tags_str = models.CharField(max_length=1024, blank=True, null=False, default='')
    persona_id = models.UUIDField(null=True, blank=True)
    label = models.CharField(max_length=64, blank=True, null=False, default='')
    notes = models.TextField(blank=True, null=False, default='')
    schedule = models.ForeignKey(CrawlSchedule, on_delete=models.SET_NULL, null=True, blank=True, editable=True)
    output_dir = models.CharField(max_length=512, null=False, blank=True, default='')

    status = ModelWithStateMachine.StatusField(choices=ModelWithStateMachine.StatusChoices, default=ModelWithStateMachine.StatusChoices.QUEUED)
    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)

    state_machine_name = 'archivebox.crawls.models.CrawlMachine'
    retry_at_field_name = 'retry_at'
    state_field_name = 'status'
    StatusChoices = ModelWithStateMachine.StatusChoices
    active_state = StatusChoices.STARTED

    snapshot_set: models.Manager['Snapshot']

    class Meta(TypedModelMeta):
        app_label = 'crawls'
        verbose_name = 'Crawl'
        verbose_name_plural = 'Crawls'

    def __str__(self):
        first_url = self.get_urls_list()[0] if self.get_urls_list() else ''
        # Show last 8 digits of UUID and more of the URL
        short_id = str(self.id)[-8:]
        return f'[...{short_id}] {first_url[:120]}'

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            from archivebox.misc.logging_util import log_worker_event
            first_url = self.get_urls_list()[0] if self.get_urls_list() else ''
            log_worker_event(
                worker_type='DB',
                event='Created Crawl',
                indent_level=1,
                metadata={
                    'id': str(self.id),
                    'first_url': first_url[:64],
                    'max_depth': self.max_depth,
                    'status': self.status,
                },
            )

    @classmethod
    def from_file(cls, source_file: Path, max_depth: int = 0, label: str = '', extractor: str = 'auto',
                  tags_str: str = '', config=None, created_by=None):
        """Create a crawl from a file containing URLs."""
        urls_content = source_file.read_text()
        crawl = cls.objects.create(
            urls=urls_content,
            extractor=extractor,
            max_depth=max_depth,
            tags_str=tags_str,
            label=label or source_file.name,
            config=config or {},
            created_by_id=getattr(created_by, 'pk', created_by) or get_or_create_system_user_pk(),
        )
        return crawl

    @property
    def api_url(self) -> str:
        return reverse_lazy('api-1:get_crawl', args=[self.id])

    @property
    def output_dir_parent(self) -> str:
        """Construct parent directory: users/{user_id}/crawls/{YYYYMMDD}"""
        date_str = self.created_at.strftime('%Y%m%d')
        return f'users/{self.created_by_id}/crawls/{date_str}'

    @property
    def output_dir_name(self) -> str:
        """Use crawl ID as directory name"""
        return str(self.id)

    def get_urls_list(self) -> list[str]:
        """Get list of URLs from urls field, filtering out comments and empty lines."""
        if not self.urls:
            return []
        return [
            url.strip()
            for url in self.urls.split('\n')
            if url.strip() and not url.strip().startswith('#')
        ]

    def get_file_path(self) -> Path | None:
        """
        Get filesystem path if this crawl references a local file.
        Checks if the first URL is a file:// URI.
        """
        urls = self.get_urls_list()
        if not urls:
            return None

        first_url = urls[0]
        if not first_url.startswith('file://'):
            return None

        # Remove file:// prefix
        path_str = first_url.replace('file://', '', 1)
        return Path(path_str)

    def create_root_snapshot(self) -> 'Snapshot':
        from archivebox.core.models import Snapshot

        first_url = self.get_urls_list()[0] if self.get_urls_list() else None
        if not first_url:
            raise ValueError(f'Crawl {self.id} has no URLs to create root snapshot from')

        try:
            return Snapshot.objects.get(crawl=self, url=first_url)
        except Snapshot.DoesNotExist:
            pass

        root_snapshot, _ = Snapshot.objects.update_or_create(
            crawl=self, url=first_url,
            defaults={
                'status': Snapshot.INITIAL_STATE,
                'retry_at': timezone.now(),
                'timestamp': str(timezone.now().timestamp()),
                'depth': 0,
            },
        )
        return root_snapshot

    def add_url(self, entry: dict) -> bool:
        """
        Add a URL to the crawl queue if not already present.

        Args:
            entry: dict with 'url', optional 'depth', 'title', 'timestamp', 'tags', 'via_snapshot', 'plugin'

        Returns:
            True if URL was added, False if skipped (duplicate or depth exceeded)
        """
        import json

        url = entry.get('url', '')
        if not url:
            return False

        depth = entry.get('depth', 1)

        # Skip if depth exceeds max_depth
        if depth > self.max_depth:
            return False

        # Skip if already a Snapshot for this crawl
        if self.snapshot_set.filter(url=url).exists():
            return False

        # Check if already in urls (parse existing JSONL entries)
        existing_urls = set()
        for line in self.urls.splitlines():
            if not line.strip():
                continue
            try:
                existing_entry = json.loads(line)
                existing_urls.add(existing_entry.get('url', ''))
            except json.JSONDecodeError:
                existing_urls.add(line.strip())

        if url in existing_urls:
            return False

        # Append as JSONL
        jsonl_entry = json.dumps(entry)
        self.urls = (self.urls.rstrip() + '\n' + jsonl_entry).lstrip('\n')
        self.save(update_fields=['urls', 'modified_at'])
        return True

    def create_snapshots_from_urls(self) -> list['Snapshot']:
        """
        Create Snapshot objects for each URL in self.urls that doesn't already exist.

        Returns:
            List of newly created Snapshot objects
        """
        import json
        from archivebox.core.models import Snapshot

        created_snapshots = []

        for line in self.urls.splitlines():
            if not line.strip():
                continue

            # Parse JSONL or plain URL
            try:
                entry = json.loads(line)
                url = entry.get('url', '')
                depth = entry.get('depth', 1)
                title = entry.get('title')
                timestamp = entry.get('timestamp')
                tags = entry.get('tags', '')
            except json.JSONDecodeError:
                url = line.strip()
                depth = 1
                title = None
                timestamp = None
                tags = ''

            if not url:
                continue

            # Skip if depth exceeds max_depth
            if depth > self.max_depth:
                continue

            # Create snapshot if doesn't exist
            snapshot, created = Snapshot.objects.get_or_create(
                url=url,
                crawl=self,
                defaults={
                    'depth': depth,
                    'title': title,
                    'timestamp': timestamp or str(timezone.now().timestamp()),
                    'status': Snapshot.INITIAL_STATE,
                    'retry_at': timezone.now(),
                    # Note: created_by removed in 0.9.0 - Snapshot inherits from Crawl
                }
            )

            if created:
                created_snapshots.append(snapshot)
                # Save tags if present
                if tags:
                    snapshot.save_tags(tags.split(','))

        return created_snapshots

    def run(self) -> 'Snapshot':
        """
        Execute this Crawl: run hooks, process JSONL, create snapshots.

        Called by the state machine when entering the 'started' state.

        Returns:
            The root Snapshot for this crawl
        """
        import time
        from pathlib import Path
        from archivebox.hooks import run_hook, discover_hooks, process_hook_records
        from archivebox.config.configset import get_config

        # Get merged config with crawl context
        config = get_config(crawl=self)

        # Discover and run on_Crawl hooks
        hooks = discover_hooks('Crawl', config=config)
        first_url = self.get_urls_list()[0] if self.get_urls_list() else ''

        for hook in hooks:
            hook_start = time.time()
            plugin_name = hook.parent.name
            output_dir = self.OUTPUT_DIR / plugin_name
            output_dir.mkdir(parents=True, exist_ok=True)

            result = run_hook(
                hook,
                output_dir=output_dir,
                config=config,
                crawl_id=str(self.id),
                source_url=first_url,
            )

            hook_elapsed = time.time() - hook_start
            if hook_elapsed > 0.5:  # Log slow hooks
                print(f'[yellow]⏱️  Hook {hook.name} took {hook_elapsed:.2f}s[/yellow]')

            # Background hook - returns None, continues running
            if result is None:
                continue

            # Foreground hook - process JSONL records
            records = result.get('records', [])
            overrides = {'crawl': self}
            process_hook_records(records, overrides=overrides)

        # Create snapshots from URLs
        root_snapshot = self.create_root_snapshot()
        self.create_snapshots_from_urls()
        return root_snapshot

    def cleanup(self):
        """Clean up background hooks and run on_CrawlEnd hooks."""
        import os
        import signal
        import time
        from pathlib import Path
        from archivebox.hooks import run_hook, discover_hooks
        from archivebox.misc.process_utils import validate_pid_file

        def is_process_alive(pid):
            """Check if a process exists."""
            try:
                os.kill(pid, 0)  # Signal 0 checks existence without killing
                return True
            except (OSError, ProcessLookupError):
                return False

        # Kill any background processes by scanning for all .pid files
        if self.OUTPUT_DIR.exists():
            for pid_file in self.OUTPUT_DIR.glob('**/*.pid'):
                # Validate PID before killing to avoid killing unrelated processes
                cmd_file = pid_file.parent / 'cmd.sh'
                if not validate_pid_file(pid_file, cmd_file):
                    # PID reused by different process or process dead
                    pid_file.unlink(missing_ok=True)
                    continue

                try:
                    pid = int(pid_file.read_text().strip())

                    # Step 1: Send SIGTERM for graceful shutdown
                    try:
                        # Try to kill process group first (handles detached processes like Chrome)
                        try:
                            os.killpg(pid, signal.SIGTERM)
                        except (OSError, ProcessLookupError):
                            # Fall back to killing just the process
                            os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        # Already dead
                        pid_file.unlink(missing_ok=True)
                        continue

                    # Step 2: Wait for graceful shutdown
                    time.sleep(2)

                    # Step 3: Check if still alive
                    if not is_process_alive(pid):
                        # Process terminated gracefully
                        pid_file.unlink(missing_ok=True)
                        continue

                    # Step 4: Process still alive, force kill ENTIRE process group with SIGKILL
                    try:
                        try:
                            # Always kill entire process group with SIGKILL (not individual processes)
                            os.killpg(pid, signal.SIGKILL)
                        except (OSError, ProcessLookupError) as e:
                            # Process group kill failed, try single process as fallback
                            os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        # Process died between check and kill
                        pid_file.unlink(missing_ok=True)
                        continue

                    # Step 5: Wait and verify death
                    time.sleep(1)

                    if is_process_alive(pid):
                        # Process is unkillable (likely in UNE state on macOS)
                        # This happens when Chrome crashes in kernel syscall (IOSurface)
                        # Log but don't block cleanup - process will remain until reboot
                        print(f'[yellow]⚠️ Process {pid} is unkillable (likely crashed in kernel). Will remain until reboot.[/yellow]')
                    else:
                        # Successfully killed
                        pid_file.unlink(missing_ok=True)

                except (ValueError, OSError) as e:
                    # Invalid PID file or permission error
                    pass

        # Run on_CrawlEnd hooks
        from archivebox.config.configset import get_config
        config = get_config(crawl=self)

        hooks = discover_hooks('CrawlEnd', config=config)
        first_url = self.get_urls_list()[0] if self.get_urls_list() else ''

        for hook in hooks:
            plugin_name = hook.parent.name
            output_dir = self.OUTPUT_DIR / plugin_name
            output_dir.mkdir(parents=True, exist_ok=True)

            result = run_hook(
                hook,
                output_dir=output_dir,
                config=config,
                crawl_id=str(self.id),
                source_url=first_url,
            )

            # Log failures but don't block
            if result and result['returncode'] != 0:
                print(f'[yellow]⚠️ CrawlEnd hook failed: {hook.name}[/yellow]')


# =============================================================================
# State Machines
# =============================================================================

class CrawlMachine(BaseStateMachine, strict_states=True):
    """
    State machine for managing Crawl lifecycle.

    Hook Lifecycle:
    ┌─────────────────────────────────────────────────────────────┐
    │ QUEUED State                                                │
    │  • Waiting for crawl to be ready (has URLs)                 │
    └─────────────────────────────────────────────────────────────┘
                            ↓ tick() when can_start()
    ┌─────────────────────────────────────────────────────────────┐
    │ STARTED State → enter_started()                             │
    │  1. crawl.run()                                             │
    │     • discover_hooks('Crawl') → finds all crawl hooks       │
    │     • For each hook:                                        │
    │       - run_hook(script, output_dir, ...)                   │
    │       - Parse JSONL from hook output                        │
    │       - process_hook_records() → creates Snapshots          │
    │     • create_root_snapshot() → root snapshot for crawl      │
    │     • create_snapshots_from_urls() → from self.urls field   │
    │                                                              │
    │  2. Snapshots process independently with their own          │
    │     state machines (see SnapshotMachine)                    │
    └─────────────────────────────────────────────────────────────┘
                            ↓ tick() when is_finished()
    ┌─────────────────────────────────────────────────────────────┐
    │ SEALED State → enter_sealed()                               │
    │  • cleanup() → runs on_CrawlEnd hooks, kills background     │
    │  • Set retry_at=None (no more processing)                   │
    └─────────────────────────────────────────────────────────────┘
    """

    model_attr_name = 'crawl'

    # States
    queued = State(value=Crawl.StatusChoices.QUEUED, initial=True)
    started = State(value=Crawl.StatusChoices.STARTED)
    sealed = State(value=Crawl.StatusChoices.SEALED, final=True)

    # Tick Event
    tick = (
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to.itself(unless='is_finished') |
        started.to(sealed, cond='is_finished')
    )

    def can_start(self) -> bool:
        if not self.crawl.urls:
            print(f'[red]⚠️ Crawl {self.crawl.id} cannot start: no URLs[/red]')
            return False
        urls_list = self.crawl.get_urls_list()
        if not urls_list:
            print(f'[red]⚠️ Crawl {self.crawl.id} cannot start: no valid URLs in urls field[/red]')
            return False
        return True

    def is_finished(self) -> bool:
        from archivebox.core.models import Snapshot

        # check that at least one snapshot exists for this crawl
        snapshots = Snapshot.objects.filter(crawl=self.crawl)
        if not snapshots.exists():
            return False

        # check if all snapshots are sealed
        # Snapshots handle their own background hooks via the step system,
        # so we just need to wait for all snapshots to reach sealed state
        if snapshots.filter(status__in=[Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED]).exists():
            return False

        return True

    @started.enter
    def enter_started(self):
        # Lock the crawl by bumping retry_at so other workers don't pick it up while we create snapshots
        self.crawl.update_and_requeue(
            retry_at=timezone.now() + timedelta(seconds=30),  # Lock for 30 seconds
        )

        try:
            # Run the crawl - runs hooks, processes JSONL, creates snapshots
            self.crawl.run()

            # Update status to STARTED once snapshots are created
            # Set retry_at to future so we don't busy-loop - wait for snapshots to process
            self.crawl.update_and_requeue(
                retry_at=timezone.now() + timedelta(seconds=5),  # Check again in 5s
                status=Crawl.StatusChoices.STARTED,
            )
        except Exception as e:
            print(f'[red]⚠️ Crawl {self.crawl.id} failed to start: {e}[/red]')
            import traceback
            traceback.print_exc()
            # Re-raise so the worker knows it failed
            raise

    def on_started_to_started(self):
        """Called when Crawl stays in started state (snapshots not sealed yet)."""
        # Bump retry_at so we check again in a few seconds
        self.crawl.update_and_requeue(
            retry_at=timezone.now() + timedelta(seconds=5),
        )

    @sealed.enter
    def enter_sealed(self):
        # Clean up background hooks and run on_CrawlEnd hooks
        self.crawl.cleanup()

        self.crawl.update_and_requeue(
            retry_at=None,
            status=Crawl.StatusChoices.SEALED,
        )


# =============================================================================
# Register State Machines
# =============================================================================

# Manually register state machines with python-statemachine registry
# (normally auto-discovered from statemachines.py, but we define them here for clarity)
registry.register(CrawlMachine)
