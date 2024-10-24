__package__ = 'archivebox.seeds'


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
    
    uri = models.URLField(max_length=255, blank=False, null=False, unique=True)              # unique source location where URLs will be loaded from
    
    extractor = models.CharField(default='auto', max_length=32)   # suggested extractor to use to load this URL source
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
        return self.uri.split('://')[0].lower()
