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
from archivebox.base_models.models import ModelWithUUID, ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats, get_or_create_system_user_pk
from archivebox.workers.models import ModelWithStateMachine, BaseStateMachine

if TYPE_CHECKING:
    from archivebox.core.models import Snapshot, ArchiveResult


class CrawlSchedule(ModelWithUUID, ModelWithNotes):
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

    @property
    def api_url(self) -> str:
        return reverse_lazy('api-1:get_crawl', args=[self.id])

    def to_json(self) -> dict:
        """
        Convert Crawl model instance to a JSON-serializable dict.
        """
        from archivebox.config import VERSION
        return {
            'type': 'Crawl',
            'schema_version': VERSION,
            'id': str(self.id),
            'urls': self.urls,
            'status': self.status,
            'max_depth': self.max_depth,
            'tags_str': self.tags_str,
            'label': self.label,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    @staticmethod
    def from_json(record: dict, overrides: dict = None):
        """
        Create or get a Crawl from a JSON dict.

        Args:
            record: Dict with 'urls' (required), optional 'max_depth', 'tags_str', 'label'
            overrides: Dict of field overrides (e.g., created_by_id)

        Returns:
            Crawl instance or None if invalid
        """
        from django.utils import timezone

        overrides = overrides or {}

        # Check if crawl already exists by ID
        crawl_id = record.get('id')
        if crawl_id:
            try:
                return Crawl.objects.get(id=crawl_id)
            except Crawl.DoesNotExist:
                pass

        # Get URLs - can be string (newline-separated) or from 'url' field
        urls = record.get('urls', '')
        if not urls and record.get('url'):
            urls = record['url']

        if not urls:
            return None

        # Create new crawl (status stays QUEUED, not started)
        crawl = Crawl.objects.create(
            urls=urls,
            max_depth=record.get('max_depth', record.get('depth', 0)),
            tags_str=record.get('tags_str', record.get('tags', '')),
            label=record.get('label', ''),
            status=Crawl.StatusChoices.QUEUED,
            retry_at=timezone.now(),
            **overrides,
        )
        return crawl

    @property
    def output_dir(self) -> Path:
        """
        Construct output directory: users/{username}/crawls/{YYYYMMDD}/{domain}/{crawl-id}
        Domain is extracted from the first URL in the crawl.
        """
        from archivebox import DATA_DIR
        from archivebox.core.models import Snapshot

        date_str = self.created_at.strftime('%Y%m%d')
        urls = self.get_urls_list()
        domain = Snapshot.extract_domain_from_url(urls[0]) if urls else 'unknown'

        return DATA_DIR / 'users' / self.created_by.username / 'crawls' / date_str / domain / str(self.id)

    def get_urls_list(self) -> list[str]:
        """Get list of URLs from urls field, filtering out comments and empty lines."""
        if not self.urls:
            return []
        return [
            url.strip()
            for url in self.urls.split('\n')
            if url.strip() and not url.strip().startswith('#')
        ]


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
        import sys
        import json
        from archivebox.core.models import Snapshot

        created_snapshots = []

        print(f'[cyan]DEBUG create_snapshots_from_urls: self.urls={repr(self.urls)}[/cyan]', file=sys.stderr)
        print(f'[cyan]DEBUG create_snapshots_from_urls: lines={self.urls.splitlines()}[/cyan]', file=sys.stderr)

        for line in self.urls.splitlines():
            if not line.strip():
                continue

            # Parse JSONL or plain URL
            try:
                entry = json.loads(line)
                url = entry.get('url', '')
                depth = entry.get('depth', 0)
                title = entry.get('title')
                timestamp = entry.get('timestamp')
                tags = entry.get('tags', '')
            except json.JSONDecodeError:
                url = line.strip()
                depth = 0
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

            # Ensure crawl -> snapshot symlink exists for both new and existing snapshots
            try:
                snapshot.ensure_crawl_symlink()
            except Exception:
                pass

        return created_snapshots

    def run(self) -> 'Snapshot | None':
        """
        Execute this Crawl: run hooks, process JSONL, create snapshots.

        Called by the state machine when entering the 'started' state.

        Returns:
            The root Snapshot for this crawl, or None for system crawls that don't create snapshots
        """
        import time
        from pathlib import Path
        from archivebox.hooks import run_hook, discover_hooks, process_hook_records
        from archivebox.config.configset import get_config

        # Debug logging to file (since stdout/stderr redirected to /dev/null in progress mode)
        debug_log = Path('/tmp/archivebox_crawl_debug.log')
        with open(debug_log, 'a') as f:
            f.write(f'\n=== Crawl.run() starting for {self.id} at {time.time()} ===\n')
            f.flush()

        # Get merged config with crawl context
        config = get_config(crawl=self)

        # Discover and run on_Crawl hooks
        with open(debug_log, 'a') as f:
            f.write(f'Discovering Crawl hooks...\n')
            f.flush()
        hooks = discover_hooks('Crawl', config=config)
        with open(debug_log, 'a') as f:
            f.write(f'Found {len(hooks)} hooks\n')
            f.flush()

        for hook in hooks:
            with open(debug_log, 'a') as f:
                f.write(f'Running hook: {hook.name}\n')
                f.flush()
            hook_start = time.time()
            plugin_name = hook.parent.name
            output_dir = self.output_dir / plugin_name
            output_dir.mkdir(parents=True, exist_ok=True)

            # Run hook using Process.launch() - returns Process model
            process = run_hook(
                hook,
                output_dir=output_dir,
                config=config,
                crawl_id=str(self.id),
                source_url=self.urls,  # Pass full newline-separated URLs
            )
            with open(debug_log, 'a') as f:
                f.write(f'Hook {hook.name} completed with status={process.status}\n')
                f.flush()

            hook_elapsed = time.time() - hook_start
            if hook_elapsed > 0.5:  # Log slow hooks
                print(f'[yellow]⏱️  Hook {hook.name} took {hook_elapsed:.2f}s[/yellow]')

            # Background hook - still running
            if process.status == process.StatusChoices.RUNNING:
                continue

            # Foreground hook - process JSONL records
            from archivebox.hooks import extract_records_from_process
            records = extract_records_from_process(process)
            if records:
                print(f'[cyan]📝 Processing {len(records)} records from {hook.name}[/cyan]')
                for record in records[:3]:  # Show first 3
                    print(f'   Record: type={record.get("type")}, keys={list(record.keys())[:5]}')
            overrides = {'crawl': self}
            stats = process_hook_records(records, overrides=overrides)
            if stats:
                print(f'[green]✓ Created: {stats}[/green]')

        # Ensure any newly declared binaries are installed before creating snapshots
        from archivebox.machine.models import Binary, Machine
        from django.utils import timezone

        machine = Machine.current()
        while True:
            pending_binaries = Binary.objects.filter(
                machine=machine,
                status=Binary.StatusChoices.QUEUED,
                retry_at__lte=timezone.now(),
            ).order_by('retry_at')
            if not pending_binaries.exists():
                break

            for binary in pending_binaries:
                try:
                    binary.sm.tick()
                except Exception:
                    continue

            # Exit if nothing else is immediately retryable
            if not Binary.objects.filter(
                machine=machine,
                status=Binary.StatusChoices.QUEUED,
                retry_at__lte=timezone.now(),
            ).exists():
                break

        # Create snapshots from all URLs in self.urls
        with open(debug_log, 'a') as f:
            f.write(f'Creating snapshots from URLs...\n')
            f.flush()
        created_snapshots = self.create_snapshots_from_urls()
        with open(debug_log, 'a') as f:
            f.write(f'Created {len(created_snapshots)} snapshots\n')
            f.write(f'=== Crawl.run() complete ===\n\n')
            f.flush()

        # Return first snapshot for this crawl (newly created or existing)
        # This ensures the crawl doesn't seal if snapshots exist, even if they weren't just created
        return self.snapshot_set.first()

    def is_finished(self) -> bool:
        """Check if crawl is finished (all snapshots sealed or no snapshots exist)."""
        from archivebox.core.models import Snapshot

        # Check if any snapshots exist for this crawl
        snapshots = Snapshot.objects.filter(crawl=self)

        # If no snapshots exist, allow finishing (e.g., archivebox://install crawls that only run hooks)
        if not snapshots.exists():
            return True

        # If snapshots exist, check if all are sealed
        if snapshots.filter(status__in=[Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED]).exists():
            return False

        return True

    def cleanup(self):
        """Clean up background hooks and run on_CrawlEnd hooks."""
        from archivebox.hooks import run_hook, discover_hooks
        from archivebox.machine.models import Process

        # Kill any background Crawl hooks using Process records
        # Find all running hook Processes that are children of this crawl's workers
        # (CrawlWorker already kills its hooks via on_shutdown, but this is backup for orphans)
        running_hooks = Process.objects.filter(
            parent__worker_type='crawl',
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
        ).distinct()

        for process in running_hooks:
            # Use Process.kill_tree() to gracefully kill parent + children
            killed_count = process.kill_tree(graceful_timeout=2.0)
            if killed_count > 0:
                print(f'[yellow]🔪 Killed {killed_count} orphaned crawl hook process(es)[/yellow]')

        # Clean up .pid files from output directory
        if self.output_dir.exists():
            for pid_file in self.output_dir.glob('**/*.pid'):
                pid_file.unlink(missing_ok=True)

        # Run on_CrawlEnd hooks
        from archivebox.config.configset import get_config
        config = get_config(crawl=self)

        hooks = discover_hooks('CrawlEnd', config=config)

        for hook in hooks:
            plugin_name = hook.parent.name
            output_dir = self.output_dir / plugin_name
            output_dir.mkdir(parents=True, exist_ok=True)

            process = run_hook(
                hook,
                output_dir=output_dir,
                config=config,
                crawl_id=str(self.id),
                source_url=self.urls,  # Pass full newline-separated URLs
            )

            # Log failures but don't block
            if process.exit_code != 0:
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

    # Tick Event (polled by workers)
    tick = (
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to(sealed, cond='is_finished')
    )

    # Manual event (triggered by last Snapshot sealing)
    seal = started.to(sealed)

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
        """Check if all Snapshots for this crawl are finished."""
        return self.crawl.is_finished()

    @started.enter
    def enter_started(self):
        import sys
        from archivebox.core.models import Snapshot

        print(f'[cyan]🔄 CrawlMachine.enter_started() - creating snapshots for {self.crawl.id}[/cyan]', file=sys.stderr)

        try:
            # Run the crawl - runs hooks, processes JSONL, creates snapshots
            first_snapshot = self.crawl.run()

            if first_snapshot:
                print(f'[cyan]🔄 Created {self.crawl.snapshot_set.count()} snapshot(s), first: {first_snapshot.url}[/cyan]', file=sys.stderr)
                # Update status to STARTED
                # Set retry_at to near future so tick() can poll and check is_finished()
                self.crawl.update_and_requeue(
                    retry_at=timezone.now() + timedelta(seconds=2),
                    status=Crawl.StatusChoices.STARTED,
                )
            else:
                # No snapshots (system crawl like archivebox://install)
                print(f'[cyan]🔄 No snapshots created, sealing crawl immediately[/cyan]', file=sys.stderr)
                # Seal immediately since there's no work to do
                self.seal()

        except Exception as e:
            print(f'[red]⚠️ Crawl {self.crawl.id} failed to start: {e}[/red]')
            import traceback
            traceback.print_exc()
            raise

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
