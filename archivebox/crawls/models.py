__package__ = 'archivebox.crawls'

from typing import TYPE_CHECKING
import uuid
from datetime import timedelta
from archivebox.uuid_compat import uuid7
from pathlib import Path

from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.conf import settings
from django.urls import reverse_lazy
from django.utils import timezone
from statemachine import State, registry
from rich import print

from archivebox.base_models.models import ModelWithUUID, ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats, get_or_create_system_user_pk
from archivebox.workers.models import ModelWithStateMachine, BaseStateMachine
from archivebox.crawls.schedule_utils import next_run_for_schedule, validate_schedule

if TYPE_CHECKING:
    from archivebox.core.models import Snapshot


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

    class Meta(ModelWithUUID.Meta, ModelWithNotes.Meta):
        app_label = 'crawls'
        verbose_name = 'Scheduled Crawl'
        verbose_name_plural = 'Scheduled Crawls'

    def __str__(self) -> str:
        urls_preview = self.template.urls[:64] if self.template and self.template.urls else ""
        return f'[{self.id}] {urls_preview} @ {self.schedule}'

    @property
    def api_url(self) -> str:
        return str(reverse_lazy('api-1:get_any', args=[self.id]))

    def save(self, *args, **kwargs):
        self.schedule = (self.schedule or '').strip()
        validate_schedule(self.schedule)
        self.label = self.label or (self.template.label if self.template else '')
        super().save(*args, **kwargs)
        if self.template:
            self.template.schedule = self
            self.template.save()

    @property
    def last_run_at(self):
        latest_crawl = self.crawl_set.order_by('-created_at').first()
        if latest_crawl:
            return latest_crawl.created_at
        if self.template:
            return self.template.created_at
        return self.created_at

    @property
    def next_run_at(self):
        return next_run_for_schedule(self.schedule, self.last_run_at)

    def is_due(self, now=None) -> bool:
        now = now or timezone.now()
        return self.is_enabled and self.next_run_at <= now

    def enqueue(self, queued_at=None) -> 'Crawl':
        queued_at = queued_at or timezone.now()
        template = self.template
        label = template.label or self.label

        return Crawl.objects.create(
            urls=template.urls,
            config=template.config or {},
            max_depth=template.max_depth,
            tags_str=template.tags_str,
            persona_id=template.persona_id,
            label=label,
            notes=template.notes,
            schedule=self,
            status=Crawl.StatusChoices.QUEUED,
            retry_at=queued_at,
            created_by=template.created_by,
        )


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

    status = ModelWithStateMachine.StatusField(choices=ModelWithStateMachine.StatusChoices, default=ModelWithStateMachine.StatusChoices.QUEUED)
    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)

    state_machine_name = 'archivebox.crawls.models.CrawlMachine'
    retry_at_field_name = 'retry_at'
    state_field_name = 'status'
    StatusChoices = ModelWithStateMachine.StatusChoices
    active_state = StatusChoices.STARTED

    schedule_id: uuid.UUID | None
    sm: 'CrawlMachine'

    snapshot_set: models.Manager['Snapshot']

    class Meta(
        ModelWithOutputDir.Meta,
        ModelWithConfig.Meta,
        ModelWithHealthStats.Meta,
        ModelWithStateMachine.Meta,
    ):
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
        return str(reverse_lazy('api-1:get_crawl', args=[self.id]))

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
    def from_json(record: dict, overrides: dict | None = None):
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

    def get_system_task(self) -> str | None:
        urls = self.get_urls_list()
        if len(urls) != 1:
            return None
        system_url = urls[0].strip().lower()
        if system_url.startswith('archivebox://'):
            return system_url
        return None

    def resolve_persona(self):
        from archivebox.personas.models import Persona

        if self.persona_id:
            persona = Persona.objects.filter(id=self.persona_id).first()
            if persona is None:
                raise Persona.DoesNotExist(f'Crawl {self.id} references missing Persona {self.persona_id}')
            return persona

        default_persona_name = str((self.config or {}).get('DEFAULT_PERSONA') or '').strip()
        if default_persona_name:
            persona, _ = Persona.objects.get_or_create(name=default_persona_name or 'Default')
            return persona

        return None


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
                tags = self.tags_str

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

    def install_declared_binaries(self, binary_names: set[str], machine=None) -> None:
        """
        Install crawl-declared Binary rows without violating the retry_at lock lifecycle.

        Correct calling pattern:
        1. Crawl hooks declare Binary records and queue them with retry_at <= now
        2. Exactly one actor claims each Binary by moving retry_at into the future
        3. Only that owner executes `.sm.tick()` and performs install side effects
        4. Everyone else waits for the claimed owner to finish instead of launching
           a second install against shared state such as the pip or npm trees

        This helper follows that contract by claiming each Binary before ticking
        it, and by waiting when another worker already owns the row. That keeps
        synchronous crawl execution compatible with the shared background runner and
        avoids duplicate installs of the same dependency.
        """
        import time
        from archivebox.machine.models import Binary, Machine

        if not binary_names:
            return

        machine = machine or Machine.current()
        lock_seconds = 600
        deadline = time.monotonic() + max(lock_seconds, len(binary_names) * lock_seconds)

        while time.monotonic() < deadline:
            unresolved_binaries = list(
                Binary.objects.filter(
                    machine=machine,
                    name__in=binary_names,
                ).exclude(
                    status=Binary.StatusChoices.INSTALLED,
                ).order_by('name')
            )
            if not unresolved_binaries:
                return

            claimed_any = False
            waiting_on_existing_owner = False
            now = timezone.now()

            for binary in unresolved_binaries:
                try:
                    if binary.tick_claimed(lock_seconds=lock_seconds):
                        claimed_any = True
                        continue
                except Exception:
                    claimed_any = True
                    continue

                binary.refresh_from_db()
                if binary.status == Binary.StatusChoices.INSTALLED:
                    claimed_any = True
                    continue
                if binary.retry_at and binary.retry_at > now:
                    waiting_on_existing_owner = True

            if claimed_any:
                continue
            if waiting_on_existing_owner:
                time.sleep(0.5)
                continue
            break

        unresolved_binaries = list(
            Binary.objects.filter(
                machine=machine,
                name__in=binary_names,
            ).exclude(
                status=Binary.StatusChoices.INSTALLED,
            ).order_by('name')
        )
        if unresolved_binaries:
            binary_details = ', '.join(
                f'{binary.name} (status={binary.status}, retry_at={binary.retry_at})'
                for binary in unresolved_binaries
            )
            raise RuntimeError(
                f'Crawl dependencies failed to install before continuing: {binary_details}'
            )

    def run(self) -> 'Snapshot | None':
        """
        Execute this Crawl: run hooks, process JSONL, create snapshots.

        Called by the state machine when entering the 'started' state.

        Returns:
            The root Snapshot for this crawl, or None for system crawls that don't create snapshots
        """
        import time
        from pathlib import Path
        from archivebox.hooks import run_hook, discover_hooks, process_hook_records, is_finite_background_hook
        from archivebox.config.configset import get_config
        from archivebox.machine.models import Binary, Machine

        # Debug logging to file (since stdout/stderr redirected to /dev/null in progress mode)
        debug_log = Path('/tmp/archivebox_crawl_debug.log')
        with open(debug_log, 'a') as f:
            f.write(f'\n=== Crawl.run() starting for {self.id} at {time.time()} ===\n')
            f.flush()

        def get_runtime_config():
            config = get_config(crawl=self)
            if persona_runtime_overrides:
                config.update(persona_runtime_overrides)
            return config

        system_task = self.get_system_task()
        if system_task == 'archivebox://update':
            from archivebox.cli.archivebox_update import process_all_db_snapshots

            process_all_db_snapshots()
            return None

        machine = Machine.current()
        declared_binary_names: set[str] = set()
        persona_runtime_overrides: dict[str, str] = {}
        persona = self.resolve_persona()
        if persona:
            base_runtime_config = get_config(crawl=self, persona=persona)
            chrome_binary = str(base_runtime_config.get('CHROME_BINARY') or '')
            persona_runtime_overrides = persona.prepare_runtime_for_crawl(
                crawl=self,
                chrome_binary=chrome_binary,
            )

        executed_crawl_hooks: set[str] = set()

        def run_crawl_hook(hook: Path) -> set[str]:
            executed_crawl_hooks.add(str(hook))
            primary_url = next(
                (line.strip() for line in self.urls.splitlines() if line.strip()),
                self.urls.strip(),
            )

            with open(debug_log, 'a') as f:
                f.write(f'Running hook: {hook.name}\n')
                f.flush()
            hook_start = time.time()
            plugin_name = hook.parent.name
            output_dir = self.output_dir / plugin_name
            output_dir.mkdir(parents=True, exist_ok=True)

            process = run_hook(
                hook,
                output_dir=output_dir,
                config=get_runtime_config(),
                crawl_id=str(self.id),
                source_url=self.urls,
                url=primary_url,
                snapshot_id=str(self.id),
            )
            with open(debug_log, 'a') as f:
                f.write(f'Hook {hook.name} completed with status={process.status}\n')
                f.flush()

            hook_elapsed = time.time() - hook_start
            if hook_elapsed > 0.5:
                print(f'[yellow]⏱️  Hook {hook.name} took {hook_elapsed:.2f}s[/yellow]')

            if process.status == process.StatusChoices.RUNNING:
                if not is_finite_background_hook(hook.name):
                    return set()
                try:
                    process.wait(timeout=process.timeout)
                except Exception:
                    return set()

            from archivebox.hooks import extract_records_from_process
            records = []
            # Finite background hooks can exit before their stdout log is fully
            # visible to our polling loop. Give successful hooks a brief chance
            # to flush JSONL records before we move on to downstream hooks.
            for delay in (0.0, 0.05, 0.1, 0.25, 0.5):
                if delay:
                    time.sleep(delay)
                records = extract_records_from_process(process)
                if records:
                    break
            if records:
                print(f'[cyan]📝 Processing {len(records)} records from {hook.name}[/cyan]')
                for record in records[:3]:
                    print(f'   Record: type={record.get("type")}, keys={list(record.keys())[:5]}')
            if system_task:
                records = [
                    record
                    for record in records
                    if record.get('type') in ('Binary', 'Machine')
                ]
            overrides = {'crawl': self}
            stats = process_hook_records(records, overrides=overrides)
            if stats:
                print(f'[green]✓ Created: {stats}[/green]')

            hook_binary_names = {
                str(record.get('name')).strip()
                for record in records
                if record.get('type') == 'Binary' and record.get('name')
            }
            hook_binary_names.discard('')
            if hook_binary_names:
                declared_binary_names.update(hook_binary_names)
            return hook_binary_names

        def resolve_provider_binaries(binary_names: set[str]) -> set[str]:
            if not binary_names:
                return set()

            resolved_binary_names = set(binary_names)

            while True:
                unresolved_binaries = list(
                    Binary.objects.filter(
                        machine=machine,
                        name__in=resolved_binary_names,
                    ).exclude(
                        status=Binary.StatusChoices.INSTALLED,
                    ).order_by('name')
                )
                if not unresolved_binaries:
                    return resolved_binary_names

                needed_provider_names: set[str] = set()
                for binary in unresolved_binaries:
                    allowed_binproviders = binary._allowed_binproviders()
                    if allowed_binproviders is None:
                        continue
                    needed_provider_names.update(allowed_binproviders)

                if not needed_provider_names:
                    return resolved_binary_names

                provider_hooks = [
                    hook
                    for hook in discover_hooks('Crawl', filter_disabled=False, config=get_runtime_config())
                    if hook.parent.name in needed_provider_names and str(hook) not in executed_crawl_hooks
                ]
                if not provider_hooks:
                    return resolved_binary_names

                for hook in provider_hooks:
                    resolved_binary_names.update(run_crawl_hook(hook))

        # Discover and run on_Crawl hooks
        with open(debug_log, 'a') as f:
            f.write('Discovering Crawl hooks...\n')
            f.flush()
        hooks = discover_hooks('Crawl', config=get_runtime_config())
        with open(debug_log, 'a') as f:
            f.write(f'Found {len(hooks)} hooks\n')
            f.flush()

        for hook in hooks:
            hook_binary_names = run_crawl_hook(hook)
            if hook_binary_names:
                self.install_declared_binaries(resolve_provider_binaries(hook_binary_names), machine=machine)

        # Safety check: don't create snapshots if any crawl-declared dependency
        # is still unresolved after all crawl hooks have run.
        self.install_declared_binaries(declared_binary_names, machine=machine)

        # Create snapshots from all URLs in self.urls
        if system_task:
            leaked_snapshots = self.snapshot_set.all()
            if leaked_snapshots.exists():
                leaked_count = leaked_snapshots.count()
                leaked_snapshots.delete()
                print(f'[yellow]⚠️  Removed {leaked_count} leaked snapshot(s) created during system crawl {system_task}[/yellow]')
            with open(debug_log, 'a') as f:
                f.write(f'Skipping snapshot creation for system crawl: {system_task}\n')
                f.write('=== Crawl.run() complete ===\n\n')
                f.flush()
            return None

        with open(debug_log, 'a') as f:
            f.write('Creating snapshots from URLs...\n')
            f.flush()
        created_snapshots = self.create_snapshots_from_urls()
        with open(debug_log, 'a') as f:
            f.write(f'Created {len(created_snapshots)} snapshots\n')
            f.write('=== Crawl.run() complete ===\n\n')
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

        running_hooks = Process.objects.filter(
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            env__CRAWL_ID=str(self.id),
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

        persona = self.resolve_persona()
        if persona:
            persona.cleanup_runtime_for_crawl(self)

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

class CrawlMachine(BaseStateMachine):
    crawl: Crawl

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
        queued.to.itself(unless='can_start')
        | queued.to(started, cond='can_start')
        | started.to(sealed, cond='is_finished')
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
                print('[cyan]🔄 No snapshots created, sealing crawl immediately[/cyan]', file=sys.stderr)
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
