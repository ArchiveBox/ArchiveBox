__package__ = 'archivebox.crawls'

from typing import TYPE_CHECKING, Iterable
from pathlib import Path
from django_stubs_ext.db.models import TypedModelMeta

from django.db import models
from django.db.models import QuerySet
from django.core.validators import MaxValueValidator, MinValueValidator 
from django.conf import settings
from django.urls import reverse_lazy
from django.utils import timezone

from archivebox.config import CONSTANTS
from base_models.models import ModelWithReadOnlyFields, ModelWithSerializers, ModelWithUUID, ModelWithKVTags, ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ABIDModel, ABIDField, AutoDateTimeField, ModelWithHealthStats, get_or_create_system_user_pk
from workers.models import ModelWithStateMachine
from tags.models import KVTag, GenericRelation

if TYPE_CHECKING:
    from core.models import Snapshot, ArchiveResult




class Seed(ModelWithReadOnlyFields, ModelWithSerializers, ModelWithUUID, ModelWithKVTags, ABIDModel, ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats):
    """
    A fountain that produces URLs (+metadata) each time it's queried e.g.
        - file:///data/sources/2024-01-02_11-57-51__cli_add.txt
        - file:///data/sources/2024-01-02_11-57-51__web_ui_add.txt
        - file:///Users/squash/Library/Application Support/Google/Chrome/Default/Bookmarks
        - https://getpocket.com/user/nikisweeting/feed
        - https://www.iana.org/assignments/uri-schemes/uri-schemes.xhtml
        - ...
    Each query of a Seed can produce the same list of URLs, or a different list each time.
    The list of URLs it returns is used to create a new Crawl and seed it with new pending Snapshots.
        
    When a crawl is created, a root_snapshot is initially created with a URI set to the Seed URI.
    The seed's preferred extractor is executed on that URI, which produces an ArchiveResult containing outlinks.
    The outlinks then get turned into new pending Snapshots under the same crawl,
    and the cycle repeats until Crawl.max_depth.

    Each consumption of a Seed by an Extractor can produce new urls, as Seeds can point to
    stateful remote services, files with contents that change, directories that have new files within, etc.
    """
    
    ### ModelWithReadOnlyFields:
    read_only_fields = ('id', 'abid', 'created_at', 'created_by', 'uri')
    
    ### Immutable fields
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)                  # unique source location where URLs will be loaded from
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    
    ### Mutable fields:
    extractor = models.CharField(default='auto', max_length=32, help_text='The parser / extractor to use to load URLs from this source (default: auto)')
    tags_str = models.CharField(max_length=255, null=False, blank=True, default='', help_text='An optional comma-separated list of tags to attach to any URLs that come from this source')
    label = models.CharField(max_length=255, null=False, blank=True, default='', help_text='A human-readable label for this seed')
    modified_at = models.DateTimeField(auto_now=True)

    ### ModelWithConfig:
    config = models.JSONField(default=dict, help_text='An optional JSON object containing extra config to put in scope when loading URLs from this source')

    ### ModelWithOutputDir:
    output_dir = models.CharField(max_length=255, null=False, blank=True, default='', help_text='The directory to store the output of this seed')

    ### ModelWithNotes:
    notes = models.TextField(blank=True, null=False, default='', help_text='Any extra notes this seed should have')

    ### ModelWithKVTags:
    tag_set = GenericRelation(
        KVTag,
        related_query_name="seed",
        content_type_field="obj_type",
        object_id_field="obj_id",
        order_by=('name',),
    )
    
    ### ABIDModel:
    abid_prefix = 'src_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.uri'
    abid_subtype_src = 'self.extractor'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True
    
    ### ModelWithOutputDir:
    output_dir = models.FilePathField(path=settings.ARCHIVE_DIR, null=False, blank=True, default='', help_text='The directory to store the output of this crawl')
    output_dir_template = 'archive/seeds/{self.created_at.strftime("%Y%m%d")}/{self.abid}'
    output_dir_symlinks = [
        ('index.json',      'self.as_json()'),
        ('config.toml',     'benedict(self.config).as_toml()'),
        ('seed/',           'self.seed.output_dir.relative_to(self.output_dir)'),
        ('persona/',        'self.persona.output_dir.relative_to(self.output_dir)'),
        ('created_by/',     'self.created_by.output_dir.relative_to(self.output_dir)'),
        ('schedule/',       'self.schedule.output_dir.relative_to(self.output_dir)'),
        ('sessions/',       '[session.output_dir for session in self.session_set.all()]'),
        ('snapshots/',      '[snapshot.output_dir for snapshot in self.snapshot_set.all()]'),
        ('archiveresults/', '[archiveresult.output_dir for archiveresult in self.archiveresult_set.all()]'),
    ]
    
    ### Managers:
    crawl_set: models.Manager['Crawl']

    class Meta:
        verbose_name = 'Seed'
        verbose_name_plural = 'Seeds'
        
        unique_together = (('created_by', 'uri', 'extractor'),('created_by', 'label'))


    @classmethod
    def from_file(cls, source_file: Path, label: str='', parser: str='auto', tag: str='', created_by: int|None=None, config: dict|None=None):
        source_path = str(source_file.resolve()).replace(str(CONSTANTS.DATA_DIR), '/data')
        
        seed, _ = cls.objects.get_or_create(
            label=label or source_file.name,
            uri=f'file://{source_path}',
            created_by_id=getattr(created_by, 'pk', created_by) or get_or_create_system_user_pk(),
            extractor=parser,
            tags_str=tag,
            config=config or {},
        )
        seed.save()
        return seed

    @property
    def source_type(self):
        # e.g. http/https://
        #      file://
        #      pocketapi://
        #      s3://
        #      etc..
        return self.uri.split('://', 1)[0].lower()

    @property
    def api_url(self) -> str:
        # /api/v1/core/seed/{uulid}
        return reverse_lazy('api-1:get_seed', args=[self.abid])  # + f'?api_key={get_or_create_api_token(request.user)}'

    @property
    def api_docs_url(self) -> str:
        return '/api/v1/docs#/Core%20Models/api_v1_core_get_seed'

    @property
    def scheduled_crawl_set(self) -> QuerySet['CrawlSchedule']:
        from crawls.models import CrawlSchedule
        return CrawlSchedule.objects.filter(template__seed_id=self.pk)

    @property
    def snapshot_set(self) -> QuerySet['Snapshot']:
        from core.models import Snapshot
        
        crawl_ids = self.crawl_set.values_list('pk', flat=True)
        return Snapshot.objects.filter(crawl_id__in=crawl_ids)




class CrawlSchedule(ModelWithReadOnlyFields, ModelWithSerializers, ModelWithUUID, ModelWithKVTags, ABIDModel, ModelWithNotes, ModelWithHealthStats):
    """
    A record for a job that should run repeatedly on a given schedule.
    
    It pulls from a given Seed and creates a new Crawl for each scheduled run.
    The new Crawl will inherit all the properties of the crawl_template Crawl.
    """
    ### ABIDModel:
    abid_prefix = 'cws_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.template.seed.uri'
    abid_subtype_src = 'self.template.persona'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True
    abid = ABIDField(prefix=abid_prefix)
    
    ### ModelWithReadOnlyFields:
    read_only_fields = ('id', 'abid', 'created_at', 'created_by', 'template_id')
    
    ### Immutable fields:
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    template: 'Crawl' = models.ForeignKey('Crawl', on_delete=models.CASCADE, null=False, blank=False, help_text='The base crawl that each new scheduled job should copy as a template')  # type: ignore
    
    ### Mutable fields
    schedule = models.CharField(max_length=64, blank=False, null=False, help_text='The schedule to run this crawl on in CRON syntax e.g. 0 0 * * * (see https://crontab.guru/)')
    is_enabled = models.BooleanField(default=True)
    label = models.CharField(max_length=64, blank=True, null=False, default='', help_text='A human-readable label for this scheduled crawl')
    notes = models.TextField(blank=True, null=False, default='', help_text='Any extra notes this crawl should have')
    modified_at = models.DateTimeField(auto_now=True)
    
    ### ModelWithKVTags:
    tag_set = GenericRelation(
        KVTag,
        related_query_name="crawlschedule",
        content_type_field="obj_type",
        object_id_field="obj_id",
        order_by=('name',),
    )
    
    ### Managers:
    crawl_set: models.Manager['Crawl']
    
    class Meta(TypedModelMeta):
        verbose_name = 'Scheduled Crawl'
        verbose_name_plural = 'Scheduled Crawls'
        
    def __str__(self) -> str:
        uri = (self.template and self.template.seed and self.template.seed.uri) or '<no url set>'
        crawl_label = self.label or (self.template and self.template.seed and self.template.seed.label) or 'Untitled Crawl'
        if self.id and self.template:
            return f'[{self.ABID}] {uri[:64]} @ {self.schedule} (Scheduled {crawl_label})'
        return f'[{self.abid_prefix}****not*saved*yet****] {uri[:64]} @ {self.schedule} (Scheduled {crawl_label})'
    
    @property
    def api_url(self) -> str:
        # /api/v1/core/crawlschedule/{uulid}
        return reverse_lazy('api-1:get_any', args=[self.abid])  # + f'?api_key={get_or_create_api_token(request.user)}'

    @property
    def api_docs_url(self) -> str:
        return '/api/v1/docs#/Core%20Models/api_v1_core_get_any'
    
    def save(self, *args, **kwargs):
        self.label = self.label or self.template.seed.label or self.template.seed.uri
        super().save(*args, **kwargs)
        
        # make sure the template crawl points to this schedule as its schedule
        self.template.schedule = self
        self.template.save()
        
    @property
    def snapshot_set(self) -> QuerySet['Snapshot']:
        from core.models import Snapshot
        
        crawl_ids = self.crawl_set.values_list('pk', flat=True)
        return Snapshot.objects.filter(crawl_id__in=crawl_ids)
    

class CrawlManager(models.Manager):
    pass

class CrawlQuerySet(models.QuerySet):
    """
    Enhanced QuerySet for Crawl that adds some useful methods.
    
    To get all the snapshots for a given set of Crawls:
        Crawl.objects.filter(seed__uri='https://example.com/some/rss.xml').snapshots() -> QuerySet[Snapshot]
    
    To get all the archiveresults for a given set of Crawls:
        Crawl.objects.filter(seed__uri='https://example.com/some/rss.xml').archiveresults() -> QuerySet[ArchiveResult]
    
    To export the list of Crawls as a CSV or JSON:
        Crawl.objects.filter(seed__uri='https://example.com/some/rss.xml').export_as_csv() -> str
        Crawl.objects.filter(seed__uri='https://example.com/some/rss.xml').export_as_json() -> str
    """
    def snapshots(self, **filter_kwargs) -> QuerySet['Snapshot']:
        return Snapshot.objects.filter(crawl_id__in=self.values_list('pk', flat=True), **filter_kwargs)
    
    def archiveresults(self) -> QuerySet['ArchiveResult']:
        return ArchiveResult.objects.filter(snapshot__crawl_id__in=self.values_list('pk', flat=True))
    
    def as_csv_str(self, keys: Iterable[str]=()) -> str:
        return '\n'.join(
            row.as_csv(keys=keys)
            for row in self.all()
        )
    
    def as_jsonl_str(self, keys: Iterable[str]=()) -> str:
        return '\n'.join([
            row.as_jsonl_row(keys=keys)
            for row in self.all()
        ])



class Crawl(ModelWithReadOnlyFields, ModelWithSerializers, ModelWithUUID, ModelWithKVTags, ABIDModel, ModelWithOutputDir, ModelWithConfig, ModelWithHealthStats, ModelWithStateMachine):
    """
    A single session of URLs to archive starting from a given Seed and expanding outwards. An "archiving session" so to speak.

    A new Crawl should be created for each loading from a Seed (because it can produce a different set of URLs every time its loaded).
    E.g. every scheduled import from an RSS feed should create a new Crawl, and more loadings from the same seed each create a new Crawl
    
    Every "Add" task triggered from the Web UI, CLI, or Scheduled Crawl should create a new Crawl with the seed set to a 
    file URI e.g. file:///sources/<date>_{ui,cli}_add.txt containing the user's input.
    """
    
    ### ModelWithReadOnlyFields:
    read_only_fields = ('id', 'abid', 'created_at', 'created_by', 'seed')
    
    ### Immutable fields:
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    seed = models.ForeignKey(Seed, on_delete=models.PROTECT, related_name='crawl_set', null=False, blank=False)
    
    ### Mutable fields:
    urls = models.TextField(blank=True, null=False, default='', help_text='The log of URLs discovered in this crawl, one per line, should be 1:1 with snapshot_set')
    config = models.JSONField(default=dict)
    max_depth = models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(4)])
    tags_str = models.CharField(max_length=1024, blank=True, null=False, default='')
    persona_id = models.UUIDField(null=True, blank=True)  # TODO: replace with self.persona = models.ForeignKey(Persona, on_delete=models.SET_NULL, null=True, blank=True, editable=True)
    label = models.CharField(max_length=64, blank=True, null=False, default='', help_text='A human-readable label for this crawl')
    notes = models.TextField(blank=True, null=False, default='', help_text='Any extra notes this crawl should have')
    schedule = models.ForeignKey(CrawlSchedule, on_delete=models.SET_NULL, null=True, blank=True, editable=True)
    modified_at = models.DateTimeField(auto_now=True)
    
    ### ModelWithKVTags:
    tag_set = GenericRelation(
        KVTag,
        related_query_name="crawl",
        content_type_field="obj_type",
        object_id_field="obj_id",
        order_by=('name',),
    )
    
    ### ModelWithStateMachine:
    state_machine_name = 'crawls.statemachines.CrawlMachine'
    retry_at_field_name = 'retry_at'
    state_field_name = 'status'
    StatusChoices = ModelWithStateMachine.StatusChoices
    active_state = StatusChoices.STARTED
    
    status = ModelWithStateMachine.StatusField(choices=StatusChoices, default=StatusChoices.QUEUED)
    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)

    ### ABIDModel:
    abid_prefix = 'cwl_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.seed.uri'
    abid_subtype_src = 'self.persona'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True
    
    ### ModelWithOutputDir:
    output_dir = models.FilePathField(path=settings.ARCHIVE_DIR, null=False, blank=True, default='', help_text='The directory to store the output of this crawl')
    output_dir_template = 'archive/crawls/{getattr(crawl, crawl.abid_ts_src).strftime("%Y%m%d")}/{crawl.abid}'
    output_dir_symlinks = [
        ('index.json', 'self.as_json'),
        ('seed/', 'self.seed.output_dir'),
        ('persona/', 'self.persona.output_dir'),
        ('created_by/', 'self.created_by.output_dir'),
        ('schedule/', 'self.schedule.output_dir'),
        ('sessions/', '[session.output_dir for session in self.session_set.all()]'),
        ('snapshots/', '[snapshot.output_dir for snapshot in self.snapshot_set.all()]'),
        ('archiveresults/', '[archiveresult.output_dir for archiveresult in self.archiveresult_set.all()]'),
    ]
    
    ### Managers:    
    snapshot_set: models.Manager['Snapshot']
    
    # @property
    # def persona(self) -> Persona:
    #     # TODO: replace with self.persona = models.ForeignKey(Persona, on_delete=models.SET_NULL, null=True, blank=True, editable=True)
    #     return self.persona_id
    

    class Meta(TypedModelMeta):
        verbose_name = 'Crawl'
        verbose_name_plural = 'Crawls'
        
    def __str__(self):
        url = (self.seed and self.seed.uri) or '<no url set>'
        parser = (self.seed and self.seed.extractor) or 'auto'
        created_at = self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else '<no timestamp set>'
        if self.id and self.seed:
            return f'[{self.ABID}] {url[:64]} ({parser}) @ {created_at} ({self.label or "Untitled Crawl"})'
        return f'[{self.abid_prefix}****not*saved*yet****] {url[:64]} ({parser}) @ {created_at} ({self.label or "Untitled Crawl"})'
        
    @classmethod
    def from_seed(cls, seed: Seed, max_depth: int=0, persona: str='Default', tags_str: str='', config: dict|None=None, created_by: int|None=None):
        crawl, _ = cls.objects.get_or_create(
            seed=seed,
            max_depth=max_depth,
            tags_str=tags_str or seed.tags_str,
            persona=persona or seed.config.get('DEFAULT_PERSONA') or 'Default',
            config=seed.config or config or {},
            created_by_id=getattr(created_by, 'pk', created_by) or seed.created_by_id,
        )
        crawl.save()
        return crawl
        
    @property
    def template(self):
        """If this crawl was created under a ScheduledCrawl, returns the original template Crawl it was based off"""
        if not self.schedule:
            return None
        return self.schedule.template

    @property
    def api_url(self) -> str:
        # /api/v1/core/crawl/{uulid}
        # TODO: implement get_crawl
        return reverse_lazy('api-1:get_crawl', args=[self.abid])  # + f'?api_key={get_or_create_api_token(request.user)}'

    @property
    def api_docs_url(self) -> str:
        return '/api/v1/docs#/Core%20Models/api_v1_core_get_crawl'
    
    def pending_snapshots(self) -> QuerySet['Snapshot']:
        return self.snapshot_set.filter(retry_at__isnull=False)
    
    def pending_archiveresults(self) -> QuerySet['ArchiveResult']:
        from core.models import ArchiveResult
        
        snapshot_ids = self.snapshot_set.values_list('id', flat=True)
        pending_archiveresults = ArchiveResult.objects.filter(snapshot_id__in=snapshot_ids, retry_at__isnull=False)
        return pending_archiveresults
    
    def create_root_snapshot(self) -> 'Snapshot':
        print(f'Crawl[{self.ABID}].create_root_snapshot()')
        from core.models import Snapshot
        
        try:
            return Snapshot.objects.get(crawl=self, url=self.seed.uri)
        except Snapshot.DoesNotExist:
            pass

        root_snapshot, _ = Snapshot.objects.update_or_create(
            crawl=self,
            url=self.seed.uri,
            defaults={
                'status': Snapshot.INITIAL_STATE,
                'retry_at': timezone.now(),
                'timestamp': str(timezone.now().timestamp()),
                # 'config': self.seed.config,
            },
        )
        root_snapshot.save()
        return root_snapshot


class Outlink(ModelWithReadOnlyFields, ModelWithSerializers, ModelWithUUID, ModelWithKVTags):
    """A record of a link found on a page, pointing to another page."""
    read_only_fields = ('id', 'src', 'dst', 'crawl', 'via')
    
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    
    src = models.URLField()   # parent page where the outlink/href was found       e.g. https://example.com/downloads
    dst = models.URLField()   # remote location the child outlink/href points to   e.g. https://example.com/downloads/some_file.pdf
    
    crawl = models.ForeignKey(Crawl, on_delete=models.CASCADE, null=False, blank=False, related_name='outlink_set')
    via = models.ForeignKey('core.ArchiveResult', on_delete=models.SET_NULL, null=True, blank=True, related_name='outlink_set')

    class Meta:
        unique_together = (('src', 'dst', 'via'),)




        
# @abx.hookimpl.on_archiveresult_created
# def exec_archiveresult_extractor_effects(archiveresult):
#     config = get_scope_config(...)
    
#     # abx.archivebox.writes.update_archiveresult_started(archiveresult, start_ts=timezone.now())
#     # abx.archivebox.events.on_archiveresult_updated(archiveresult)
    
#     # check if it should be skipped
#     if not abx.archivebox.reads.get_archiveresult_should_run(archiveresult, config):
#         abx.archivebox.writes.update_archiveresult_skipped(archiveresult, status='skipped')
#         abx.archivebox.events.on_archiveresult_skipped(archiveresult, config)
#         return
    
#     # run the extractor method and save the output back to the archiveresult
#     try:
#         output = abx.archivebox.effects.exec_archiveresult_extractor(archiveresult, config)
#         abx.archivebox.writes.update_archiveresult_succeeded(archiveresult, output=output, error=None, end_ts=timezone.now())
#     except Exception as e:
#         abx.archivebox.writes.update_archiveresult_failed(archiveresult, error=e, end_ts=timezone.now())
    
#     # bump the modified time on the archiveresult and Snapshot
#     abx.archivebox.events.on_archiveresult_updated(archiveresult)
#     abx.archivebox.events.on_snapshot_updated(archiveresult.snapshot)
    

# @abx.hookimpl.reads.get_outlink_parents
# def get_outlink_parents(url, crawl_pk=None, config=None):
#     scope = Q(dst=url)
#     if crawl_pk:
#         scope = scope | Q(via__snapshot__crawl_id=crawl_pk)
    
#     parent = list(Outlink.objects.filter(scope))
#     if not parent:
#         # base case: we reached the top of the chain, no more parents left
#         return []
    
#     # recursive case: there is another parent above us, get its parents
#     yield parent[0]
#     yield from get_outlink_parents(parent[0].src, crawl_pk=crawl_pk, config=config)


