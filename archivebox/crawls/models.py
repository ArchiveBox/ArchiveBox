__package__ = 'archivebox.crawls'

from django_stubs_ext.db.models import TypedModelMeta

from django.db import models
from django.db.models import Q
from django.core.validators import MaxValueValidator, MinValueValidator 
from django.conf import settings
from django.utils import timezone
from django.urls import reverse_lazy

from seeds.models import Seed

from abid_utils.models import ABIDModel, ABIDField, AutoDateTimeField, ModelWithHealthStats


class CrawlSchedule(ABIDModel, ModelWithHealthStats):
    """
    A record for a job that should run repeatedly on a given schedule.
    
    It pulls from a given Seed and creates a new Crawl for each scheduled run.
    The new Crawl will inherit all the properties of the crawl_template Crawl.
    """
    abid_prefix = 'sch_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.created_by_id'
    abid_subtype_src = 'self.schedule'
    abid_rand_src = 'self.id'
    
    schedule = models.CharField(max_length=64, blank=False, null=False)
    
    is_enabled = models.BooleanField(default=True)
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False)
    
    crawl_set: models.Manager['Crawl']
    
    @property
    def template(self):
        """The base crawl that each new scheduled job should copy as a template"""
        return self.crawl_set.first()


class Crawl(ABIDModel, ModelWithHealthStats):
    """
    A single session of URLs to archive starting from a given Seed and expanding outwards. An "archiving session" so to speak.

    A new Crawl should be created for each loading from a Seed (because it can produce a different set of URLs every time its loaded).
    E.g. every scheduled import from an RSS feed should create a new Crawl, and more loadings from the same seed each create a new Crawl
    
    Every "Add" task triggered from the Web UI, CLI, or Scheduled Crawl should create a new Crawl with the seed set to a 
    file URI e.g. file:///sources/<date>_{ui,cli}_add.txt containing the user's input.
    """
    abid_prefix = 'crl_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.seed.uri'
    abid_subtype_src = 'self.persona_id'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True

    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False, related_name='crawl_set')
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    seed = models.ForeignKey(Seed, on_delete=models.PROTECT, related_name='crawl_set', null=False, blank=False)
    max_depth = models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(4)])
    tags_str = models.CharField(max_length=1024, blank=True, null=False, default='')
    persona = models.CharField(max_length=32, blank=True, null=False, default='auto')
    config = models.JSONField(default=dict)
    
    schedule = models.ForeignKey(CrawlSchedule, on_delete=models.SET_NULL, null=True, blank=True, editable=True)
    
    # crawler = models.CharField(choices=CRAWLER_CHOICES, default='breadth_first', max_length=32)
    # tags = models.ManyToManyField(Tag, blank=True, related_name='crawl_set', through='CrawlTag')
    # schedule = models.JSONField()
    # config = models.JSONField()
    
    # snapshot_set: models.Manager['Snapshot']
    

    class Meta(TypedModelMeta):
        verbose_name = 'Crawl'
        verbose_name_plural = 'Crawls'
        
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


