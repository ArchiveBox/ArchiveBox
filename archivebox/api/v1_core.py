__package__ = 'archivebox.api'

import math
from uuid import UUID
from typing import List, Optional, Union, Any, Annotated
from datetime import datetime

from django.db.models import Model, Q
from django.http import HttpRequest
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.shortcuts import redirect
from django.utils import timezone

from ninja import Router, Schema, FilterLookup, FilterSchema, Query
from ninja.pagination import paginate, PaginationBase
from ninja.errors import HttpError

from archivebox.core.models import Snapshot, ArchiveResult, Tag
from archivebox.crawls.models import Crawl
from archivebox.api.v1_crawls import CrawlSchema


router = Router(tags=['Core Models'])


class CustomPagination(PaginationBase):
    class Input(PaginationBase.Input):
        limit: int = 200
        offset: int = 0
        page: int = 0

    class Output(PaginationBase.Output):
        total_items: int
        total_pages: int
        page: int
        limit: int
        offset: int
        num_items: int
        items: List[Any]

    def paginate_queryset(self, queryset, pagination: Input, request: HttpRequest, **params):
        limit = min(pagination.limit, 500)
        offset = pagination.offset or (pagination.page * limit)
        total = queryset.count()
        total_pages = math.ceil(total / limit)
        current_page = math.ceil(offset / (limit + 1))
        items = queryset[offset : offset + limit]
        return {
            'total_items': total,
            'total_pages': total_pages,
            'page': current_page,
            'limit': limit,
            'offset': offset,
            'num_items': len(items),
            'items': items,
        }


### ArchiveResult #########################################################################

class MinimalArchiveResultSchema(Schema):
    TYPE: str = 'core.models.ArchiveResult'
    id: UUID
    created_at: datetime | None
    modified_at: datetime | None
    created_by_id: str
    created_by_username: str
    status: str
    retry_at: datetime | None
    plugin: str
    hook_name: str
    process_id: UUID | None
    cmd_version: str | None
    cmd: list[str] | None
    pwd: str | None
    output_str: str
    output_json: dict | None
    output_files: dict | None
    output_size: int
    output_mimetypes: str
    start_ts: datetime | None
    end_ts: datetime | None

    @staticmethod
    def resolve_created_by_id(obj):
        return str(obj.created_by.pk)

    @staticmethod
    def resolve_created_by_username(obj) -> str:
        return obj.created_by.username


class ArchiveResultSchema(MinimalArchiveResultSchema):
    TYPE: str = 'core.models.ArchiveResult'
    snapshot_id: UUID
    snapshot_timestamp: str
    snapshot_url: str
    snapshot_tags: List[str]

    @staticmethod
    def resolve_snapshot_timestamp(obj):
        return obj.snapshot.timestamp

    @staticmethod
    def resolve_snapshot_url(obj):
        return obj.snapshot.url

    @staticmethod
    def resolve_snapshot_id(obj):
        return obj.snapshot_id

    @staticmethod
    def resolve_snapshot_tags(obj):
        return sorted(tag.name for tag in obj.snapshot.tags.all())


class ArchiveResultFilterSchema(FilterSchema):
    id: Annotated[Optional[str], FilterLookup(['id__startswith', 'snapshot__id__startswith', 'snapshot__timestamp__startswith'])] = None
    search: Annotated[Optional[str], FilterLookup(['snapshot__url__icontains', 'snapshot__title__icontains', 'snapshot__tags__name__icontains', 'plugin', 'output_str__icontains', 'id__startswith', 'snapshot__id__startswith', 'snapshot__timestamp__startswith'])] = None
    snapshot_id: Annotated[Optional[str], FilterLookup(['snapshot__id__startswith', 'snapshot__timestamp__startswith'])] = None
    snapshot_url: Annotated[Optional[str], FilterLookup('snapshot__url__icontains')] = None
    snapshot_tag: Annotated[Optional[str], FilterLookup('snapshot__tags__name__icontains')] = None
    status: Annotated[Optional[str], FilterLookup('status')] = None
    output_str: Annotated[Optional[str], FilterLookup('output_str__icontains')] = None
    plugin: Annotated[Optional[str], FilterLookup('plugin__icontains')] = None
    hook_name: Annotated[Optional[str], FilterLookup('hook_name__icontains')] = None
    process_id: Annotated[Optional[str], FilterLookup('process__id__startswith')] = None
    cmd: Annotated[Optional[str], FilterLookup('cmd__0__icontains')] = None
    pwd: Annotated[Optional[str], FilterLookup('pwd__icontains')] = None
    cmd_version: Annotated[Optional[str], FilterLookup('cmd_version')] = None
    created_at: Annotated[Optional[datetime], FilterLookup('created_at')] = None
    created_at__gte: Annotated[Optional[datetime], FilterLookup('created_at__gte')] = None
    created_at__lt: Annotated[Optional[datetime], FilterLookup('created_at__lt')] = None


@router.get("/archiveresults", response=List[ArchiveResultSchema], url_name="get_archiveresult")
@paginate(CustomPagination)
def get_archiveresults(request: HttpRequest, filters: Query[ArchiveResultFilterSchema]):
    """List all ArchiveResult entries matching these filters."""
    return filters.filter(ArchiveResult.objects.all()).distinct()


@router.get("/archiveresult/{archiveresult_id}", response=ArchiveResultSchema, url_name="get_archiveresult")
def get_archiveresult(request: HttpRequest, archiveresult_id: str):
    """Get a specific ArchiveResult by id."""
    return ArchiveResult.objects.get(Q(id__icontains=archiveresult_id))


### Snapshot #########################################################################

class SnapshotSchema(Schema):
    TYPE: str = 'core.models.Snapshot'
    id: UUID
    created_by_id: str
    created_by_username: str
    created_at: datetime
    modified_at: datetime
    status: str
    retry_at: datetime | None
    bookmarked_at: datetime
    downloaded_at: Optional[datetime]
    url: str
    tags: List[str]
    title: Optional[str]
    timestamp: str
    archive_path: str
    num_archiveresults: int
    archiveresults: List[MinimalArchiveResultSchema]

    @staticmethod
    def resolve_created_by_id(obj):
        return str(obj.created_by.pk)

    @staticmethod
    def resolve_created_by_username(obj):
        return obj.created_by.username

    @staticmethod
    def resolve_tags(obj):
        return sorted(tag.name for tag in obj.tags.all())

    @staticmethod
    def resolve_num_archiveresults(obj, context):
        return obj.archiveresult_set.all().distinct().count()

    @staticmethod
    def resolve_archiveresults(obj, context):
        if bool(getattr(context['request'], 'with_archiveresults', False)):
            return obj.archiveresult_set.all().distinct()
        return ArchiveResult.objects.none()


class SnapshotUpdateSchema(Schema):
    status: str | None = None
    retry_at: datetime | None = None
    tags: Optional[List[str]] = None


class SnapshotCreateSchema(Schema):
    url: str
    crawl_id: Optional[str] = None
    depth: int = 0
    title: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None


class SnapshotDeleteResponseSchema(Schema):
    success: bool
    snapshot_id: str
    crawl_id: str
    deleted_count: int


def normalize_tag_list(tags: Optional[List[str]] = None) -> List[str]:
    return [tag.strip() for tag in (tags or []) if tag and tag.strip()]


class SnapshotFilterSchema(FilterSchema):
    id: Annotated[Optional[str], FilterLookup(['id__icontains', 'timestamp__startswith'])] = None
    created_by_id: Annotated[Optional[str], FilterLookup('crawl__created_by_id')] = None
    created_by_username: Annotated[Optional[str], FilterLookup('crawl__created_by__username__icontains')] = None
    created_at__gte: Annotated[Optional[datetime], FilterLookup('created_at__gte')] = None
    created_at__lt: Annotated[Optional[datetime], FilterLookup('created_at__lt')] = None
    created_at: Annotated[Optional[datetime], FilterLookup('created_at')] = None
    modified_at: Annotated[Optional[datetime], FilterLookup('modified_at')] = None
    modified_at__gte: Annotated[Optional[datetime], FilterLookup('modified_at__gte')] = None
    modified_at__lt: Annotated[Optional[datetime], FilterLookup('modified_at__lt')] = None
    search: Annotated[Optional[str], FilterLookup(['url__icontains', 'title__icontains', 'tags__name__icontains', 'id__icontains', 'timestamp__startswith'])] = None
    url: Annotated[Optional[str], FilterLookup('url')] = None
    tag: Annotated[Optional[str], FilterLookup('tags__name')] = None
    title: Annotated[Optional[str], FilterLookup('title__icontains')] = None
    timestamp: Annotated[Optional[str], FilterLookup('timestamp__startswith')] = None
    bookmarked_at__gte: Annotated[Optional[datetime], FilterLookup('bookmarked_at__gte')] = None
    bookmarked_at__lt: Annotated[Optional[datetime], FilterLookup('bookmarked_at__lt')] = None


@router.get("/snapshots", response=List[SnapshotSchema], url_name="get_snapshots")
@paginate(CustomPagination)
def get_snapshots(request: HttpRequest, filters: Query[SnapshotFilterSchema], with_archiveresults: bool = False):
    """List all Snapshot entries matching these filters."""
    setattr(request, 'with_archiveresults', with_archiveresults)
    return filters.filter(Snapshot.objects.all()).distinct()


@router.get("/snapshot/{snapshot_id}", response=SnapshotSchema, url_name="get_snapshot")
def get_snapshot(request: HttpRequest, snapshot_id: str, with_archiveresults: bool = True):
    """Get a specific Snapshot by id."""
    setattr(request, 'with_archiveresults', with_archiveresults)
    try:
        return Snapshot.objects.get(Q(id__startswith=snapshot_id) | Q(timestamp__startswith=snapshot_id))
    except Snapshot.DoesNotExist:
        return Snapshot.objects.get(Q(id__icontains=snapshot_id))


@router.post("/snapshots", response=SnapshotSchema, url_name="create_snapshot")
def create_snapshot(request: HttpRequest, data: SnapshotCreateSchema):
    tags = normalize_tag_list(data.tags)
    if data.status is not None and data.status not in Snapshot.StatusChoices.values:
        raise HttpError(400, f'Invalid status: {data.status}')
    if not data.url.strip():
        raise HttpError(400, 'URL is required')
    if data.depth not in (0, 1, 2, 3, 4):
        raise HttpError(400, 'depth must be between 0 and 4')

    if data.crawl_id:
        crawl = Crawl.objects.get(id__icontains=data.crawl_id)
        crawl_tags = normalize_tag_list(crawl.tags_str.split(','))
        tags = tags or crawl_tags
    else:
        crawl = Crawl.objects.create(
            urls=data.url,
            max_depth=max(data.depth, 0),
            tags_str=','.join(tags),
            status=Crawl.StatusChoices.QUEUED,
            retry_at=timezone.now(),
            created_by=request.user if isinstance(request.user, User) else None,
        )

    snapshot_defaults = {
        'depth': data.depth,
        'title': data.title,
        'timestamp': str(timezone.now().timestamp()),
        'status': data.status or Snapshot.StatusChoices.QUEUED,
        'retry_at': timezone.now(),
    }
    snapshot, _ = Snapshot.objects.get_or_create(
        url=data.url,
        crawl=crawl,
        defaults=snapshot_defaults,
    )

    update_fields: List[str] = []
    if data.title is not None and snapshot.title != data.title:
        snapshot.title = data.title
        update_fields.append('title')
    if data.status is not None and snapshot.status != data.status:
        if data.status not in Snapshot.StatusChoices.values:
            raise HttpError(400, f'Invalid status: {data.status}')
        snapshot.status = data.status
        update_fields.append('status')
    if update_fields:
        update_fields.append('modified_at')
        snapshot.save(update_fields=update_fields)

    if tags:
        snapshot.save_tags(tags)

    try:
        snapshot.ensure_crawl_symlink()
    except Exception:
        pass

    setattr(request, 'with_archiveresults', False)
    return snapshot


@router.patch("/snapshot/{snapshot_id}", response=SnapshotSchema, url_name="patch_snapshot")
def patch_snapshot(request: HttpRequest, snapshot_id: str, data: SnapshotUpdateSchema):
    """Update a snapshot (e.g., set status=sealed to cancel queued work)."""
    try:
        snapshot = Snapshot.objects.get(Q(id__startswith=snapshot_id) | Q(timestamp__startswith=snapshot_id))
    except Snapshot.DoesNotExist:
        snapshot = Snapshot.objects.get(Q(id__icontains=snapshot_id))

    payload = data.dict(exclude_unset=True)
    update_fields = ['modified_at']
    tags = payload.pop('tags', None)

    if 'status' in payload:
        if payload['status'] not in Snapshot.StatusChoices.values:
            raise HttpError(400, f'Invalid status: {payload["status"]}')
        snapshot.status = payload['status']
        if snapshot.status == Snapshot.StatusChoices.SEALED and 'retry_at' not in payload:
            snapshot.retry_at = None
        update_fields.append('status')

    if 'retry_at' in payload:
        snapshot.retry_at = payload['retry_at']
        update_fields.append('retry_at')

    if tags is not None:
        snapshot.save_tags(normalize_tag_list(tags))

    snapshot.save(update_fields=update_fields)
    setattr(request, 'with_archiveresults', False)
    return snapshot


@router.delete("/snapshot/{snapshot_id}", response=SnapshotDeleteResponseSchema, url_name="delete_snapshot")
def delete_snapshot(request: HttpRequest, snapshot_id: str):
    snapshot = get_snapshot(request, snapshot_id, with_archiveresults=False)
    snapshot_id_str = str(snapshot.id)
    crawl_id_str = str(snapshot.crawl.pk)
    deleted_count, _ = snapshot.delete()
    return {
        'success': True,
        'snapshot_id': snapshot_id_str,
        'crawl_id': crawl_id_str,
        'deleted_count': deleted_count,
    }


### Tag #########################################################################

class TagSchema(Schema):
    TYPE: str = 'core.models.Tag'
    id: int
    modified_at: datetime
    created_at: datetime
    created_by_id: str
    created_by_username: str
    name: str
    slug: str
    num_snapshots: int
    snapshots: List[SnapshotSchema]

    @staticmethod
    def resolve_created_by_id(obj):
        return str(obj.created_by_id)

    @staticmethod
    def resolve_created_by_username(obj):
        user_model = get_user_model()
        user = user_model.objects.get(id=obj.created_by_id)
        username = getattr(user, 'username', None)
        return username if isinstance(username, str) else str(user)

    @staticmethod
    def resolve_num_snapshots(obj, context):
        return obj.snapshot_set.all().distinct().count()

    @staticmethod
    def resolve_snapshots(obj, context):
        if bool(getattr(context['request'], 'with_snapshots', False)):
            return obj.snapshot_set.all().distinct()
        return Snapshot.objects.none()


@router.get("/tags", response=List[TagSchema], url_name="get_tags")
@paginate(CustomPagination)
def get_tags(request: HttpRequest):
    setattr(request, 'with_snapshots', False)
    setattr(request, 'with_archiveresults', False)
    return Tag.objects.all().distinct()


@router.get("/tag/{tag_id}", response=TagSchema, url_name="get_tag")
def get_tag(request: HttpRequest, tag_id: str, with_snapshots: bool = True):
    setattr(request, 'with_snapshots', with_snapshots)
    setattr(request, 'with_archiveresults', False)
    try:
        return Tag.objects.get(id__icontains=tag_id)
    except (Tag.DoesNotExist, ValidationError):
        return Tag.objects.get(slug__icontains=tag_id)


@router.get("/any/{id}", response=Union[SnapshotSchema, ArchiveResultSchema, TagSchema, CrawlSchema], url_name="get_any", summary="Get any object by its ID")
def get_any(request: HttpRequest, id: str):
    """Get any object by its ID (e.g. snapshot, archiveresult, tag, crawl, etc.)."""
    setattr(request, 'with_snapshots', False)
    setattr(request, 'with_archiveresults', False)

    for getter in [get_snapshot, get_archiveresult, get_tag]:
        try:
            response = getter(request, id)
            if isinstance(response, Model):
                return redirect(f"/api/v1/{response._meta.app_label}/{response._meta.model_name}/{response.id}?{request.META['QUERY_STRING']}")
        except Exception:
            pass

    try:
        from archivebox.api.v1_crawls import get_crawl
        response = get_crawl(request, id)
        if isinstance(response, Model):
            return redirect(f"/api/v1/{response._meta.app_label}/{response._meta.model_name}/{response.id}?{request.META['QUERY_STRING']}")
    except Exception:
        pass

    raise HttpError(404, 'Object with given ID not found')


### Tag Editor API Endpoints #########################################################################

class TagAutocompleteSchema(Schema):
    tags: List[dict]


class TagCreateSchema(Schema):
    name: str


class TagCreateResponseSchema(Schema):
    success: bool
    tag_id: int
    tag_name: str
    created: bool


class TagSnapshotRequestSchema(Schema):
    snapshot_id: str
    tag_name: Optional[str] = None
    tag_id: Optional[int] = None


class TagSnapshotResponseSchema(Schema):
    success: bool
    tag_id: int
    tag_name: str


@router.get("/tags/autocomplete/", response=TagAutocompleteSchema, url_name="tags_autocomplete")
def tags_autocomplete(request: HttpRequest, q: str = ""):
    """Return tags matching the query for autocomplete."""
    if not q:
        # Return all tags if no query (limited to 50)
        tags = Tag.objects.all().order_by('name')[:50]
    else:
        tags = Tag.objects.filter(name__icontains=q).order_by('name')[:20]

    return {
        'tags': [{'id': tag.pk, 'name': tag.name, 'slug': tag.slug} for tag in tags]
    }


@router.post("/tags/create/", response=TagCreateResponseSchema, url_name="tags_create")
def tags_create(request: HttpRequest, data: TagCreateSchema):
    """Create a new tag or return existing one."""
    name = data.name.strip()
    if not name:
        raise HttpError(400, 'Tag name is required')

    tag, created = Tag.objects.get_or_create(
        name__iexact=name,
        defaults={
            'name': name,
            'created_by': request.user if request.user.is_authenticated else None,
        }
    )

    # If found by case-insensitive match, use that tag
    if not created:
        existing_tag = Tag.objects.filter(name__iexact=name).first()
        if existing_tag is None:
            raise HttpError(500, 'Failed to load existing tag after get_or_create')
        tag = existing_tag

    return {
        'success': True,
        'tag_id': tag.pk,
        'tag_name': tag.name,
        'created': created,
    }


@router.post("/tags/add-to-snapshot/", response=TagSnapshotResponseSchema, url_name="tags_add_to_snapshot")
def tags_add_to_snapshot(request: HttpRequest, data: TagSnapshotRequestSchema):
    """Add a tag to a snapshot. Creates the tag if it doesn't exist."""
    # Get the snapshot
    try:
        snapshot = Snapshot.objects.get(
            Q(id__startswith=data.snapshot_id) | Q(timestamp__startswith=data.snapshot_id)
        )
    except Snapshot.DoesNotExist:
        raise HttpError(404, 'Snapshot not found')
    except Snapshot.MultipleObjectsReturned:
        snapshot = Snapshot.objects.filter(
            Q(id__startswith=data.snapshot_id) | Q(timestamp__startswith=data.snapshot_id)
        ).first()
        if snapshot is None:
            raise HttpError(404, 'Snapshot not found')

    # Get or create the tag
    if data.tag_name:
        name = data.tag_name.strip()
        if not name:
            raise HttpError(400, 'Tag name is required')

        tag, _ = Tag.objects.get_or_create(
            name__iexact=name,
            defaults={
                'name': name,
                'created_by': request.user if request.user.is_authenticated else None,
            }
        )
        # If found by case-insensitive match, use that tag
        existing_tag = Tag.objects.filter(name__iexact=name).first()
        if existing_tag is not None:
            tag = existing_tag
    elif data.tag_id:
        try:
            tag = Tag.objects.get(pk=data.tag_id)
        except Tag.DoesNotExist:
            raise HttpError(404, 'Tag not found')
    else:
        raise HttpError(400, 'Either tag_name or tag_id is required')

    # Add the tag to the snapshot
    snapshot.tags.add(tag.pk)

    return {
        'success': True,
        'tag_id': tag.pk,
        'tag_name': tag.name,
    }


@router.post("/tags/remove-from-snapshot/", response=TagSnapshotResponseSchema, url_name="tags_remove_from_snapshot")
def tags_remove_from_snapshot(request: HttpRequest, data: TagSnapshotRequestSchema):
    """Remove a tag from a snapshot."""
    # Get the snapshot
    try:
        snapshot = Snapshot.objects.get(
            Q(id__startswith=data.snapshot_id) | Q(timestamp__startswith=data.snapshot_id)
        )
    except Snapshot.DoesNotExist:
        raise HttpError(404, 'Snapshot not found')
    except Snapshot.MultipleObjectsReturned:
        snapshot = Snapshot.objects.filter(
            Q(id__startswith=data.snapshot_id) | Q(timestamp__startswith=data.snapshot_id)
        ).first()
        if snapshot is None:
            raise HttpError(404, 'Snapshot not found')

    # Get the tag
    if data.tag_id:
        try:
            tag = Tag.objects.get(pk=data.tag_id)
        except Tag.DoesNotExist:
            raise HttpError(404, 'Tag not found')
    elif data.tag_name:
        try:
            tag = Tag.objects.get(name__iexact=data.tag_name.strip())
        except Tag.DoesNotExist:
            raise HttpError(404, 'Tag not found')
    else:
        raise HttpError(400, 'Either tag_name or tag_id is required')

    # Remove the tag from the snapshot
    snapshot.tags.remove(tag.pk)

    return {
        'success': True,
        'tag_id': tag.pk,
        'tag_name': tag.name,
    }
