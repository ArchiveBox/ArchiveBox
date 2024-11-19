__package__ = 'archivebox.crawls'

from typing import TYPE_CHECKING
from django_stubs_ext.db.models import TypedModelMeta

from django.db import models
from django.db.models import QuerySet
from django.core.validators import MaxValueValidator, MinValueValidator 
from django.conf import settings
from django.urls import reverse_lazy
from django.utils import timezone

from workers.models import ModelWithStateMachine

if TYPE_CHECKING:
    from core.models import Snapshot, ArchiveResult

from seeds.models import Seed

from abid_utils.models import ABIDModel, ABIDField, AutoDateTimeField, ModelWithHealthStats


class CrawlSchedule(ABIDModel, ModelWithHealthStats):
    """
    A record for a job that should run repeatedly on a given schedule.
    
    It pulls from a given Seed and creates a new Crawl for each scheduled run.
    The new Crawl will inherit all the properties of the crawl_template Crawl.
    """
    abid_prefix = 'cws_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.created_by_id'
    abid_subtype_src = 'self.schedule'
    abid_rand_src = 'self.id'
    
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)
    
    schedule = models.CharField(max_length=64, blank=False, null=False, help_text='The schedule to run this crawl on in CRON syntax e.g. 0 0 * * * (see https://crontab.guru/)')
    label = models.CharField(max_length=64, blank=True, null=False, default='', help_text='A human-readable label for this scheduled crawl')
    notes = models.TextField(blank=True, null=False, default='', help_text='Any extra notes this crawl should have')
    
    template: 'Crawl' = models.ForeignKey('Crawl', on_delete=models.CASCADE, null=False, blank=False, help_text='The base crawl that each new scheduled job should copy as a template')  # type: ignore
    
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False)
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    
    is_enabled = models.BooleanField(default=True)
    
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
    

    

class Crawl(ABIDModel, ModelWithHealthStats, ModelWithStateMachine):
    """
    A single session of URLs to archive starting from a given Seed and expanding outwards. An "archiving session" so to speak.

    A new Crawl should be created for each loading from a Seed (because it can produce a different set of URLs every time its loaded).
    E.g. every scheduled import from an RSS feed should create a new Crawl, and more loadings from the same seed each create a new Crawl
    
    Every "Add" task triggered from the Web UI, CLI, or Scheduled Crawl should create a new Crawl with the seed set to a 
    file URI e.g. file:///sources/<date>_{ui,cli}_add.txt containing the user's input.
    """
    abid_prefix = 'cwl_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.seed.uri'
    abid_subtype_src = 'self.persona'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True
    
    state_machine_name = 'crawls.statemachines.CrawlMachine'
    retry_at_field_name = 'retry_at'
    state_field_name = 'status'
    StatusChoices = ModelWithStateMachine.StatusChoices
    active_state = StatusChoices.STARTED
    
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False, related_name='crawl_set')
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    
    status = ModelWithStateMachine.StatusField(choices=StatusChoices, default=StatusChoices.QUEUED)
    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)

    seed = models.ForeignKey(Seed, on_delete=models.PROTECT, related_name='crawl_set', null=False, blank=False)
    
    label = models.CharField(max_length=64, blank=True, null=False, default='', help_text='A human-readable label for this crawl')
    notes = models.TextField(blank=True, null=False, default='', help_text='Any extra notes this crawl should have')
    
    max_depth = models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(4)])
    tags_str = models.CharField(max_length=1024, blank=True, null=False, default='')
    persona = models.CharField(max_length=32, blank=True, null=False, default='auto')
    config = models.JSONField(default=dict)
    
    schedule = models.ForeignKey(CrawlSchedule, on_delete=models.SET_NULL, null=True, blank=True, editable=True)
    
    # crawler = models.CharField(choices=CRAWLER_CHOICES, default='breadth_first', max_length=32)
    # tags = models.ManyToManyField(Tag, blank=True, related_name='crawl_set', through='CrawlTag')
    # schedule = models.JSONField()
    # config = models.JSONField()
    
    snapshot_set: models.Manager['Snapshot']
    

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


class Outlink(models.Model):
    """A record of a link found on a page, pointing to another page."""
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


