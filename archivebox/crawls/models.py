__package__ = 'archivebox.crawls'

import time

import abx
import abx.archivebox.events
import abx.hookimpl

from datetime import datetime

from django_stubs_ext.db.models import TypedModelMeta

from django.db import models
from django.db.models import Q
from django.core.validators import MaxValueValidator, MinValueValidator 
from django.conf import settings
from django.utils import timezone
from django.utils.functional import cached_property
from django.urls import reverse_lazy

from pathlib import Path


from abid_utils.models import ABIDModel, ABIDField, AutoDateTimeField, ModelWithHealthStats

from ..extractors import EXTRACTOR_CHOICES


class Seed(ABIDModel, ModelWithHealthStats):
    """
    A fountain that produces URLs (+metadata) e.g.
        - file://data/sources/2024-01-02_11-57-51__cli_add.txt
        - file://data/sources/2024-01-02_11-57-51__web_ui_add.txt
        - file:///Users/squash/Library/Application Support/Google/Chrome/Default/Bookmarks
        - https://getpocket.com/user/nikisweeting/feed
        - ...
        
    When a crawl is created, a root_snapshot is initially created whos URI is the Seed URI.
    The seed's preferred extractor is executed on the Snapshot, which produces an ArchiveResult.
    The ArchiveResult (ideally) then contains some outlink URLs, which get turned into new Snapshots.
    Then the cycle repeats up until Crawl.max_depth.

    Each consumption of a Seed by an Extractor can produce new urls, as Seeds can point to
    stateful remote services, files whos contents change, etc.
    """
    uri = models.URLField(max_length=255, blank=False, null=False, unique=True)              # unique source location where URLs will be loaded from
    
    extractor = models.CharField(choices=EXTRACTOR_CHOICES, default='auto', max_length=32)   # suggested extractor to use to load this URL source
    tags_str = models.CharField(max_length=255, null=False, blank=True, default='')          # tags to attach to any URLs that come from this source
    config = models.JSONField(default=dict)                                                  # extra config to put in scope when loading URLs from this source
    
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False)

    @property
    def source_type(self):
        # e.g. http/https://
        #      file://
        #      pocketapi://
        #      s3://
        #      etc..
        return self.uri.split(':')[0]


class CrawlSchedule(ABIDModel, ModelWithHealthStats):
    """
    A record for a job that should run repeatedly on a given schedule.
    
    It pulls from a given Seed and creates a new Crawl for each scheduled run.
    The new Crawl will inherit all the properties of the crawl_template Crawl.
    """
    abid_prefix = 'sch_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.crawl.abid'
    abid_subtype_src = '"04"'
    abid_rand_src = 'self.id'
    
    schedule = models.CharField(max_length=64, blank=False, null=False)
    
    is_enabled = models.BooleanField(default=True)
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False)


class Crawl(ABIDModel, ModelWithHealthStats):
    """
    A single session of URLs to archive starting from a given Seed and expanding outwards. An "archiving session" so to speak.

    A new Crawl should be created for each loading from a Seed (because it can produce a different set of URLs every time its loaded).
    E.g. every scheduled import from an RSS feed should create a new Crawl.
    Every "Add" task triggered from the Web UI or CLI should create a new Crawl.
    """
    abid_prefix = 'crl_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.seed_id'
    abid_subtype_src = 'self.persona_id'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True

    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False, related_name='crawl_set')
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    seed = models.ForeignKey(Seed, on_delete=models.CASCADE, related_name='crawl_set', null=False, blank=False)
    max_depth = models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(4)])
    tags_str = models.CharField(max_length=1024, blank=True, null=False, default='')
    persona = models.CharField(max_length=32, blank=True, null=False, default='auto')
    config = models.JSONField(default=dict)
    
    schedule = models.ForeignKey(CrawlSchedule, null=True, blank=True, editable=True)
    
    # crawler = models.CharField(choices=CRAWLER_CHOICES, default='breadth_first', max_length=32)
    # tags = models.ManyToManyField(Tag, blank=True, related_name='crawl_set', through='CrawlTag')
    # schedule = models.JSONField()
    # config = models.JSONField()
    
    # snapshot_set: models.Manager['Snapshot']
    

    class Meta(TypedModelMeta):
        verbose_name = 'Crawl'
        verbose_name_plural = 'Crawls'

    @property
    def api_url(self) -> str:
        # /api/v1/core/crawl/{uulid}
        # TODO: implement get_crawl
        return reverse_lazy('api-1:get_crawl', args=[self.abid])  # + f'?api_key={get_or_create_api_token(request.user)}'

    @property
    def api_docs_url(self) -> str:
        return '/api/v1/docs#/Core%20Models/api_v1_core_get_crawl'


class Outlink(models.Model):
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    
    src = models.URLField()   # parent page where the outlink/href was found       e.g. https://example.com/downloads
    dst = models.URLField()   # remote location the child outlink/href points to   e.g. https://example.com/downloads/some_file.pdf
    
    via = models.ForeignKey(ArchiveResult, related_name='outlink_set')



def scheduler_runloop():
    # abx.archivebox.events.on_scheduler_runloop_start(timezone.now(), machine=Machine.objects.get_current_machine())

    while True:
        # abx.archivebox.events.on_scheduler_tick_start(timezone.now(), machine=Machine.objects.get_current_machine())
        
        scheduled_crawls = CrawlSchedule.objects.filter(is_enabled=True)
        scheduled_crawls_due = scheduled_crawls.filter(next_run_at__lte=timezone.now())
        
        for scheduled_crawl in scheduled_crawls_due:
            try:
                abx.archivebox.events.on_crawl_schedule_tick(scheduled_crawl)
            except Exception as e:
                abx.archivebox.events.on_crawl_schedule_failure(timezone.now(), machine=Machine.objects.get_current_machine(), error=e, schedule=scheduled_crawl)
        
        # abx.archivebox.events.on_scheduler_tick_end(timezone.now(), machine=Machine.objects.get_current_machine(), tasks=scheduled_tasks_due)
        time.sleep(1)


def create_crawl_from_ui_action(urls, extractor, credentials, depth, tags_str, persona, created_by, crawl_config):
    if seed_is_remote(urls, extractor, credentials):
        # user's seed is a remote source that will provide the urls (e.g. RSS feed URL, Pocket API, etc.)
        uri, extractor, credentials = abx.archivebox.effects.check_remote_seed_connection(urls, extractor, credentials, created_by)
    else:
        # user's seed is some raw text they provided to parse for urls, save it to a file then load the file as a Seed
        uri = abx.archivebox.writes.write_raw_urls_to_local_file(urls, extractor, tags_str, created_by)  # file:///data/sources/some_import.txt
    
    seed = abx.archivebox.writes.get_or_create_seed(uri=remote_uri, extractor, credentials, created_by)
    # abx.archivebox.events.on_seed_created(seed)
        
    crawl = abx.archivebox.writes.create_crawl(seed=seed, depth=depth, tags_str=tags_str, persona=persona, created_by=created_by, config=crawl_config, schedule=None)
    abx.archivebox.events.on_crawl_created(crawl)


@abx.hookimpl.on_crawl_schedule_tick
def create_crawl_from_crawl_schedule_if_due(crawl_schedule):
    # make sure it's not too early to run this scheduled import (makes this function indepmpotent / safe to call multiple times / every second)
    if timezone.now() < crawl_schedule.next_run_at:
        # it's not time to run it yet, wait for the next tick
        return
    else:
        # we're going to run it now, bump the next run time so that no one else runs it at the same time as us
        abx.archivebox.writes.update_crawl_schedule_next_run_at(crawl_schedule, next_run_at=crawl_schedule.next_run_at + crawl_schedule.interval)
    
    crawl_to_copy = None
    try:
        crawl_to_copy = crawl_schedule.crawl_set.first()  # alternatively use .last() to copy most recent crawl instead of very first crawl
    except Crawl.DoesNotExist:
        # there is no template crawl to base the next one off of
        # user must add at least one crawl to a schedule that serves as the template for all future repeated crawls
        return
    
    new_crawl = abx.archivebox.writes.create_crawl_copy(crawl_to_copy=crawl_to_copy, schedule=crawl_schedule)
    abx.archivebox.events.on_crawl_created(new_crawl)


@abx.hookimpl.on_crawl_created
def create_root_snapshot(crawl):
    # create a snapshot for the seed URI which kicks off the crawl
    # only a single extractor will run on it, which will produce outlinks which get added back to the crawl
    root_snapshot, created = abx.archivebox.writes.get_or_create_snapshot(crawl=crawl, url=crawl.seed.uri, config={
        'extractors': (
            abx.archivebox.reads.get_extractors_that_produce_outlinks()
            if crawl.seed.extractor == 'auto' else
            [crawl.seed.extractor]
        ),
        **crawl.seed.config,
    })
    if created:
        abx.archivebox.events.on_snapshot_created(root_snapshot)
        abx.archivebox.writes.update_crawl_stats(started_at=timezone.now())


@abx.hookimpl.on_snapshot_created
def create_archiveresults_pending_from_snapshot(snapshot, config):
    config = get_scope_config(
        # defaults=settings.CONFIG_FROM_DEFAULTS,
        # configfile=settings.CONFIG_FROM_FILE,
        # environment=settings.CONFIG_FROM_ENVIRONMENT,
        persona=archiveresult.snapshot.crawl.persona,
        seed=archiveresult.snapshot.crawl.seed,
        crawl=archiveresult.snapshot.crawl,
        snapshot=archiveresult.snapshot,
        archiveresult=archiveresult,
        # extra_config=extra_config,
    )
    
    extractors = abx.archivebox.reads.get_extractors_for_snapshot(snapshot, config)
    for extractor in extractors:
        archiveresult, created = abx.archivebox.writes.get_or_create_archiveresult_pending(
            snapshot=snapshot,
            extractor=extractor,
            status='pending'
        )
        if created:
            abx.archivebox.events.on_archiveresult_created(archiveresult)

        
@abx.hookimpl.on_archiveresult_created
def exec_archiveresult_extractor_effects(archiveresult):
    config = get_scope_config(...)
    
    # abx.archivebox.writes.update_archiveresult_started(archiveresult, start_ts=timezone.now())
    # abx.archivebox.events.on_archiveresult_updated(archiveresult)
    
    # check if it should be skipped
    if not abx.archivebox.reads.get_archiveresult_should_run(archiveresult, config):
        abx.archivebox.writes.update_archiveresult_skipped(archiveresult, status='skipped')
        abx.archivebox.events.on_archiveresult_skipped(archiveresult, config)
        return
    
    # run the extractor method and save the output back to the archiveresult
    try:
        output = abx.archivebox.effects.exec_archiveresult_extractor(archiveresult, config)
        abx.archivebox.writes.update_archiveresult_succeeded(archiveresult, output=output, error=None, end_ts=timezone.now())
    except Exception as e:
        abx.archivebox.writes.update_archiveresult_failed(archiveresult, error=e, end_ts=timezone.now())
    
    # bump the modified time on the archiveresult and Snapshot
    abx.archivebox.events.on_archiveresult_updated(archiveresult)
    abx.archivebox.events.on_snapshot_updated(archiveresult.snapshot)
    

@abx.hookimpl.on_archiveresult_updated
def create_snapshots_pending_from_archiveresult_outlinks(archiveresult):
    config = get_scope_config(...)
    
    # check if extractor has finished succesfully, if not, dont bother checking for outlinks
    if not archiveresult.status == 'succeeded':
        return
    
    # check if we have already reached the maximum recursion depth
    hops_to_here = abx.archivebox.reads.get_outlink_parents(crawl_pk=archiveresult.snapshot.crawl_id, url=archiveresult.url, config=config)
    if len(hops_to_here) >= archiveresult.crawl.max_depth +1:
        return
    
    # parse the output to get outlink url_entries
    discovered_urls = abx.archivebox.reads.get_archiveresult_discovered_url_entries(archiveresult, config=config)
    
    for url_entry in discovered_urls:
        abx.archivebox.writes.create_outlink_record(src=archiveresult.snapshot.url, dst=url_entry.url, via=archiveresult)
        abx.archivebox.writes.create_snapshot(crawl=archiveresult.snapshot.crawl, url_entry=url_entry)
        
    # abx.archivebox.events.on_crawl_updated(archiveresult.snapshot.crawl)

@abx.hookimpl.reads.get_outlink_parents
def get_outlink_parents(url, crawl_pk=None, config=None):
    scope = Q(dst=url)
    if crawl_pk:
        scope = scope | Q(via__snapshot__crawl_id=crawl_pk)
    
    parent = list(Outlink.objects.filter(scope))
    if not parent:
        # base case: we reached the top of the chain, no more parents left
        return []
    
    # recursive case: there is another parent above us, get its parents
    yield parent[0]
    yield from get_outlink_parents(parent[0].src, crawl_pk=crawl_pk, config=config)


