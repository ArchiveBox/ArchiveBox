__package__ = 'archivebox.crawls'

from typing import TYPE_CHECKING, Iterable
from archivebox.uuid_compat import uuid7
from pathlib import Path

from django.db import models
from django.db.models import QuerySet
from django.core.validators import MaxValueValidator, MinValueValidator
from django.conf import settings
from django.urls import reverse_lazy
from django.utils import timezone
from django_stubs_ext.db.models import TypedModelMeta

from archivebox.config import CONSTANTS
from archivebox.base_models.models import ModelWithSerializers, ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats, get_or_create_system_user_pk
from workers.models import ModelWithStateMachine

if TYPE_CHECKING:
    from core.models import Snapshot, ArchiveResult


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
    config = models.JSONField(default=dict)
    max_depth = models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(4)])
    tags_str = models.CharField(max_length=1024, blank=True, null=False, default='')
    persona_id = models.UUIDField(null=True, blank=True)
    label = models.CharField(max_length=64, blank=True, null=False, default='')
    notes = models.TextField(blank=True, null=False, default='')
    schedule = models.ForeignKey(CrawlSchedule, on_delete=models.SET_NULL, null=True, blank=True, editable=True)
    output_dir = models.FilePathField(path=settings.ARCHIVE_DIR, null=False, blank=True, default='')

    status = ModelWithStateMachine.StatusField(choices=ModelWithStateMachine.StatusChoices, default=ModelWithStateMachine.StatusChoices.QUEUED)
    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)

    state_machine_name = 'crawls.statemachines.CrawlMachine'
    retry_at_field_name = 'retry_at'
    state_field_name = 'status'
    StatusChoices = ModelWithStateMachine.StatusChoices
    active_state = StatusChoices.STARTED

    snapshot_set: models.Manager['Snapshot']

    class Meta(TypedModelMeta):
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
        from core.models import Snapshot

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
                'created_by_id': self.created_by_id,
                'depth': 0,
            },
        )
        return root_snapshot

    def add_url(self, entry: dict) -> bool:
        """
        Add a URL to the crawl queue if not already present.

        Args:
            entry: dict with 'url', optional 'depth', 'title', 'timestamp', 'tags', 'via_snapshot', 'via_extractor'

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
        from core.models import Snapshot

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
                    'created_by_id': self.created_by_id,
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
        Execute this Crawl by creating the root snapshot and processing queued URLs.

        Called by the state machine when entering the 'started' state.

        Returns:
            The root Snapshot for this crawl
        """
        root_snapshot = self.create_root_snapshot()
        self.create_snapshots_from_urls()
        return root_snapshot
