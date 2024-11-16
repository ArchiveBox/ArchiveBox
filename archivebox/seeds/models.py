__package__ = 'archivebox.seeds'

from typing import TYPE_CHECKING
from pathlib import Path

from django.db import models
from django.db.models import QuerySet
from django.conf import settings
from django.urls import reverse_lazy

from archivebox.config import CONSTANTS
from abid_utils.models import ABIDModel, ABIDField, AutoDateTimeField, ModelWithHealthStats, get_or_create_system_user_pk

if TYPE_CHECKING:
    from crawls.models import Crawl, CrawlSchedule
    from core.models import Snapshot


class Seed(ABIDModel, ModelWithHealthStats):
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
    
    abid_prefix = 'src_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.uri'
    abid_subtype_src = 'self.extractor'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True
    
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)
    
    uri = models.URLField(max_length=2000, blank=False, null=False)                          # unique source location where URLs will be loaded from
    label = models.CharField(max_length=255, null=False, blank=True, default='', help_text='A human-readable label for this seed')
    notes = models.TextField(blank=True, null=False, default='', help_text='Any extra notes this seed should have')
    
    extractor = models.CharField(default='auto', max_length=32, help_text='The parser / extractor to use to load URLs from this source (default: auto)')
    tags_str = models.CharField(max_length=255, null=False, blank=True, default='', help_text='An optional comma-separated list of tags to attach to any URLs that come from this source')
    config = models.JSONField(default=dict, help_text='An optional JSON object containing extra config to put in scope when loading URLs from this source')
    
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False)


    crawl_set: models.Manager['Crawl']

    class Meta:
        verbose_name = 'Seed'
        verbose_name_plural = 'Seeds'
        
        unique_together = (('created_by', 'uri', 'extractor'),)


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
