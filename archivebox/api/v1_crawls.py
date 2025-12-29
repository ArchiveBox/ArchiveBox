__package__ = 'archivebox.api'

from uuid import UUID
from typing import List
from datetime import datetime

from django.db.models import Q
from django.contrib.auth import get_user_model

from ninja import Router, Schema

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl

from .auth import API_AUTH_METHODS

router = Router(tags=['Crawl Models'], auth=API_AUTH_METHODS)


class CrawlSchema(Schema):
    TYPE: str = 'crawls.models.Crawl'

    id: UUID

    modified_at: datetime
    created_at: datetime
    created_by_id: str
    created_by_username: str

    status: str
    retry_at: datetime | None

    urls: str
    extractor: str
    max_depth: int
    tags_str: str
    config: dict

    # snapshots: List[SnapshotSchema]

    @staticmethod
    def resolve_created_by_id(obj):
        return str(obj.created_by_id)

    @staticmethod
    def resolve_created_by_username(obj):
        User = get_user_model()
        return User.objects.get(id=obj.created_by_id).username

    @staticmethod
    def resolve_snapshots(obj, context):
        if context['request'].with_snapshots:
            return obj.snapshot_set.all().distinct()
        return Snapshot.objects.none()


@router.get("/crawls", response=List[CrawlSchema], url_name="get_crawls")
def get_crawls(request):
    return Crawl.objects.all().distinct()

@router.get("/crawl/{crawl_id}", response=CrawlSchema | str, url_name="get_crawl")
def get_crawl(request, crawl_id: str, as_rss: bool=False, with_snapshots: bool=False, with_archiveresults: bool=False):
    """Get a specific Crawl by id."""
    request.with_snapshots = with_snapshots
    request.with_archiveresults = with_archiveresults
    crawl = Crawl.objects.get(id__icontains=crawl_id)
    
    if crawl and as_rss:
        # return snapshots as XML rss feed
        urls = [
            {'url': snapshot.url, 'title': snapshot.title, 'bookmarked_at': snapshot.bookmarked_at, 'tags': snapshot.tags_str}
            for snapshot in crawl.snapshot_set.all()
        ]
        xml = '<rss version="2.0"><channel>'
        for url in urls:
            xml += f'<item><url>{url["url"]}</url><title>{url["title"]}</title><bookmarked_at>{url["bookmarked_at"]}</bookmarked_at><tags>{url["tags"]}</tags></item>'
        xml += '</channel></rss>'
        return xml
    
    return crawl

