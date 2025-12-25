__package__ = 'archivebox.crawls'

from typing import TYPE_CHECKING, Iterable
from uuid import uuid7
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


class Seed(ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    modified_at = models.DateTimeField(auto_now=True)

    uri = models.URLField(max_length=2048)
    extractor = models.CharField(default='auto', max_length=32)
    tags_str = models.CharField(max_length=255, null=False, blank=True, default='')
    label = models.CharField(max_length=255, null=False, blank=True, default='')
    config = models.JSONField(default=dict)
    output_dir = models.FilePathField(path=settings.ARCHIVE_DIR, null=False, blank=True, default='')
    notes = models.TextField(blank=True, null=False, default='')

    crawl_set: models.Manager['Crawl']

    class Meta:
        verbose_name = 'Seed'
        verbose_name_plural = 'Seeds'
        unique_together = (('created_by', 'uri', 'extractor'), ('created_by', 'label'))

    def __str__(self):
        return f'[{self.id}] {self.uri[:64]}'

    @classmethod
    def from_file(cls, source_file: Path, label: str = '', parser: str = 'auto', tag: str = '', created_by=None, config=None):
        source_path = str(source_file.resolve()).replace(str(CONSTANTS.DATA_DIR), '/data')
        seed, _ = cls.objects.get_or_create(
            label=label or source_file.name, uri=f'file://{source_path}',
            created_by_id=getattr(created_by, 'pk', created_by) or get_or_create_system_user_pk(),
            extractor=parser, tags_str=tag, config=config or {},
        )
        return seed

    @property
    def source_type(self):
        return self.uri.split('://', 1)[0].lower()

    @property
    def api_url(self) -> str:
        return reverse_lazy('api-1:get_seed', args=[self.id])

    @property
    def snapshot_set(self) -> QuerySet['Snapshot']:
        from core.models import Snapshot
        return Snapshot.objects.filter(crawl_id__in=self.crawl_set.values_list('pk', flat=True))


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
        return f'[{self.id}] {self.template.seed.uri[:64] if self.template and self.template.seed else ""} @ {self.schedule}'

    @property
    def api_url(self) -> str:
        return reverse_lazy('api-1:get_any', args=[self.id])

    def save(self, *args, **kwargs):
        self.label = self.label or (self.template.seed.label if self.template and self.template.seed else '')
        super().save(*args, **kwargs)
        if self.template:
            self.template.schedule = self
            self.template.save()


class Crawl(ModelWithOutputDir, ModelWithConfig, ModelWithHealthStats, ModelWithStateMachine):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    modified_at = models.DateTimeField(auto_now=True)

    seed = models.ForeignKey(Seed, on_delete=models.PROTECT, related_name='crawl_set', null=False, blank=False)
    urls = models.TextField(blank=True, null=False, default='')
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
        return f'[{self.id}] {self.seed.uri[:64] if self.seed else ""}'

    @classmethod
    def from_seed(cls, seed: Seed, max_depth: int = 0, persona: str = 'Default', tags_str: str = '', config=None, created_by=None):
        crawl, _ = cls.objects.get_or_create(
            seed=seed, max_depth=max_depth, tags_str=tags_str or seed.tags_str,
            config=seed.config or config or {},
            created_by_id=getattr(created_by, 'pk', created_by) or seed.created_by_id,
        )
        return crawl

    @property
    def api_url(self) -> str:
        return reverse_lazy('api-1:get_crawl', args=[self.id])

    def create_root_snapshot(self) -> 'Snapshot':
        from core.models import Snapshot
        try:
            return Snapshot.objects.get(crawl=self, url=self.seed.uri)
        except Snapshot.DoesNotExist:
            pass
        root_snapshot, _ = Snapshot.objects.update_or_create(
            crawl=self, url=self.seed.uri,
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
