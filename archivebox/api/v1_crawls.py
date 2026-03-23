__package__ = "archivebox.api"

from uuid import UUID
from datetime import datetime
from django.http import HttpRequest
from django.utils import timezone

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User

from ninja import Router, Schema
from ninja.errors import HttpError

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl

from .auth import API_AUTH_METHODS

router = Router(tags=["Crawl Models"], auth=API_AUTH_METHODS)


class CrawlSchema(Schema):
    TYPE: str = "crawls.models.Crawl"

    id: UUID

    modified_at: datetime
    created_at: datetime
    created_by_id: str
    created_by_username: str

    status: str
    retry_at: datetime | None

    urls: str
    max_depth: int
    max_urls: int
    max_size: int
    tags_str: str
    config: dict

    # snapshots: List[SnapshotSchema]

    @staticmethod
    def resolve_created_by_id(obj):
        return str(obj.created_by_id)

    @staticmethod
    def resolve_created_by_username(obj):
        user_model = get_user_model()
        user = user_model.objects.get(id=obj.created_by_id)
        username = getattr(user, "username", None)
        return username if isinstance(username, str) else str(user)

    @staticmethod
    def resolve_snapshots(obj, context):
        if bool(getattr(context["request"], "with_snapshots", False)):
            return obj.snapshot_set.all().distinct()
        return Snapshot.objects.none()


class CrawlUpdateSchema(Schema):
    status: str | None = None
    retry_at: datetime | None = None
    tags: list[str] | None = None
    tags_str: str | None = None


class CrawlCreateSchema(Schema):
    urls: list[str]
    max_depth: int = 0
    max_urls: int = 0
    max_size: int = 0
    tags: list[str] | None = None
    tags_str: str = ""
    label: str = ""
    notes: str = ""
    config: dict = {}


class CrawlDeleteResponseSchema(Schema):
    success: bool
    crawl_id: str
    deleted_count: int
    deleted_snapshots: int


def normalize_tag_list(tags: list[str] | None = None, tags_str: str = "") -> list[str]:
    if tags is not None:
        return [tag.strip() for tag in tags if tag and tag.strip()]
    return [tag.strip() for tag in tags_str.split(",") if tag.strip()]


@router.get("/crawls", response=list[CrawlSchema], url_name="get_crawls")
def get_crawls(request: HttpRequest):
    return Crawl.objects.all().distinct()


@router.post("/crawls", response=CrawlSchema, url_name="create_crawl")
def create_crawl(request: HttpRequest, data: CrawlCreateSchema):
    urls = [url.strip() for url in data.urls if url and url.strip()]
    if not urls:
        raise HttpError(400, "At least one URL is required")
    if data.max_depth not in (0, 1, 2, 3, 4):
        raise HttpError(400, "max_depth must be between 0 and 4")
    if data.max_urls < 0:
        raise HttpError(400, "max_urls must be >= 0")
    if data.max_size < 0:
        raise HttpError(400, "max_size must be >= 0")

    tags = normalize_tag_list(data.tags, data.tags_str)
    crawl = Crawl.objects.create(
        urls="\n".join(urls),
        max_depth=data.max_depth,
        max_urls=data.max_urls,
        max_size=data.max_size,
        tags_str=",".join(tags),
        label=data.label,
        notes=data.notes,
        config=data.config,
        status=Crawl.StatusChoices.QUEUED,
        retry_at=timezone.now(),
        created_by=request.user if isinstance(request.user, User) else None,
    )
    crawl.create_snapshots_from_urls()
    return crawl


@router.get("/crawl/{crawl_id}", response=CrawlSchema | str, url_name="get_crawl")
def get_crawl(request: HttpRequest, crawl_id: str, as_rss: bool = False, with_snapshots: bool = False, with_archiveresults: bool = False):
    """Get a specific Crawl by id."""
    setattr(request, "with_snapshots", with_snapshots)
    setattr(request, "with_archiveresults", with_archiveresults)
    crawl = Crawl.objects.get(id__icontains=crawl_id)

    if crawl and as_rss:
        # return snapshots as XML rss feed
        urls = [
            {"url": snapshot.url, "title": snapshot.title, "bookmarked_at": snapshot.bookmarked_at, "tags": snapshot.tags_str}
            for snapshot in crawl.snapshot_set.all()
        ]
        xml = '<rss version="2.0"><channel>'
        for url in urls:
            xml += f"<item><url>{url['url']}</url><title>{url['title']}</title><bookmarked_at>{url['bookmarked_at']}</bookmarked_at><tags>{url['tags']}</tags></item>"
        xml += "</channel></rss>"
        return xml

    return crawl


@router.patch("/crawl/{crawl_id}", response=CrawlSchema, url_name="patch_crawl")
def patch_crawl(request: HttpRequest, crawl_id: str, data: CrawlUpdateSchema):
    """Update a crawl (e.g., set status=sealed to cancel queued work)."""
    crawl = Crawl.objects.get(id__icontains=crawl_id)
    payload = data.dict(exclude_unset=True)
    update_fields = ["modified_at"]

    tags = payload.pop("tags", None)
    tags_str = payload.pop("tags_str", None)
    if tags is not None or tags_str is not None:
        crawl.tags_str = ",".join(normalize_tag_list(tags, tags_str or ""))
        update_fields.append("tags_str")

    if "status" in payload:
        if payload["status"] not in Crawl.StatusChoices.values:
            raise HttpError(400, f"Invalid status: {payload['status']}")
        crawl.status = payload["status"]
        if crawl.status == Crawl.StatusChoices.SEALED and "retry_at" not in payload:
            crawl.retry_at = None
        update_fields.append("status")

    if "retry_at" in payload:
        crawl.retry_at = payload["retry_at"]
        update_fields.append("retry_at")

    crawl.save(update_fields=update_fields)

    if payload.get("status") == Crawl.StatusChoices.SEALED:
        Snapshot.objects.filter(
            crawl=crawl,
            status__in=[Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED],
        ).update(
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
            modified_at=timezone.now(),
        )
    return crawl


@router.delete("/crawl/{crawl_id}", response=CrawlDeleteResponseSchema, url_name="delete_crawl")
def delete_crawl(request: HttpRequest, crawl_id: str):
    crawl = Crawl.objects.get(id__icontains=crawl_id)
    crawl_id_str = str(crawl.id)
    snapshot_count = crawl.snapshot_set.count()
    deleted_count, _ = crawl.delete()
    return {
        "success": True,
        "crawl_id": crawl_id_str,
        "deleted_count": deleted_count,
        "deleted_snapshots": snapshot_count,
    }
