__package__ = 'archivebox.api'

import math
from uuid import UUID
from typing import List, Optional, Union, Any
from datetime import datetime

from django.db.models import Q
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.shortcuts import redirect

from ninja import Router, Schema, FilterSchema, Field, Query
from ninja.pagination import paginate, PaginationBase
from ninja.errors import HttpError

from archivebox.core.models import Snapshot, ArchiveResult, Tag
from archivebox.api.v1_crawls import CrawlSchema


router = Router(tags=['Core Models'])


class CustomPagination(PaginationBase):
    class Input(Schema):
        limit: int = 200
        offset: int = 0
        page: int = 0

    class Output(Schema):
        total_items: int
        total_pages: int
        page: int
        limit: int
        offset: int
        num_items: int
        items: List[Any]

    def paginate_queryset(self, queryset, pagination: Input, **params):
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
    id: Optional[str] = Field(None, q=['id__startswith', 'snapshot__id__startswith', 'snapshot__timestamp__startswith'])
    search: Optional[str] = Field(None, q=['snapshot__url__icontains', 'snapshot__title__icontains', 'snapshot__tags__name__icontains', 'plugin', 'output_str__icontains', 'id__startswith', 'snapshot__id__startswith', 'snapshot__timestamp__startswith'])
    snapshot_id: Optional[str] = Field(None, q=['snapshot__id__startswith', 'snapshot__timestamp__startswith'])
    snapshot_url: Optional[str] = Field(None, q='snapshot__url__icontains')
    snapshot_tag: Optional[str] = Field(None, q='snapshot__tags__name__icontains')
    status: Optional[str] = Field(None, q='status')
    output_str: Optional[str] = Field(None, q='output_str__icontains')
    plugin: Optional[str] = Field(None, q='plugin__icontains')
    hook_name: Optional[str] = Field(None, q='hook_name__icontains')
    process_id: Optional[str] = Field(None, q='process__id__startswith')
    cmd: Optional[str] = Field(None, q='cmd__0__icontains')
    pwd: Optional[str] = Field(None, q='pwd__icontains')
    cmd_version: Optional[str] = Field(None, q='cmd_version')
    created_at: Optional[datetime] = Field(None, q='created_at')
    created_at__gte: Optional[datetime] = Field(None, q='created_at__gte')
    created_at__lt: Optional[datetime] = Field(None, q='created_at__lt')


@router.get("/archiveresults", response=List[ArchiveResultSchema], url_name="get_archiveresult")
@paginate(CustomPagination)
def get_archiveresults(request, filters: ArchiveResultFilterSchema = Query(...)):
    """List all ArchiveResult entries matching these filters."""
    return filters.filter(ArchiveResult.objects.all()).distinct()


@router.get("/archiveresult/{archiveresult_id}", response=ArchiveResultSchema, url_name="get_archiveresult")
def get_archiveresult(request, archiveresult_id: str):
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
        if context['request'].with_archiveresults:
            return obj.archiveresult_set.all().distinct()
        return ArchiveResult.objects.none()


class SnapshotFilterSchema(FilterSchema):
    id: Optional[str] = Field(None, q=['id__icontains', 'timestamp__startswith'])
    created_by_id: str = Field(None, q='crawl__created_by_id')
    created_by_username: str = Field(None, q='crawl__created_by__username__icontains')
    created_at__gte: datetime = Field(None, q='created_at__gte')
    created_at__lt: datetime = Field(None, q='created_at__lt')
    created_at: datetime = Field(None, q='created_at')
    modified_at: datetime = Field(None, q='modified_at')
    modified_at__gte: datetime = Field(None, q='modified_at__gte')
    modified_at__lt: datetime = Field(None, q='modified_at__lt')
    search: Optional[str] = Field(None, q=['url__icontains', 'title__icontains', 'tags__name__icontains', 'id__icontains', 'timestamp__startswith'])
    url: Optional[str] = Field(None, q='url')
    tag: Optional[str] = Field(None, q='tags__name')
    title: Optional[str] = Field(None, q='title__icontains')
    timestamp: Optional[str] = Field(None, q='timestamp__startswith')
    bookmarked_at__gte: Optional[datetime] = Field(None, q='bookmarked_at__gte')
    bookmarked_at__lt: Optional[datetime] = Field(None, q='bookmarked_at__lt')


@router.get("/snapshots", response=List[SnapshotSchema], url_name="get_snapshots")
@paginate(CustomPagination)
def get_snapshots(request, filters: SnapshotFilterSchema = Query(...), with_archiveresults: bool = False):
    """List all Snapshot entries matching these filters."""
    request.with_archiveresults = with_archiveresults
    return filters.filter(Snapshot.objects.all()).distinct()


@router.get("/snapshot/{snapshot_id}", response=SnapshotSchema, url_name="get_snapshot")
def get_snapshot(request, snapshot_id: str, with_archiveresults: bool = True):
    """Get a specific Snapshot by id."""
    request.with_archiveresults = with_archiveresults
    try:
        return Snapshot.objects.get(Q(id__startswith=snapshot_id) | Q(timestamp__startswith=snapshot_id))
    except Snapshot.DoesNotExist:
        return Snapshot.objects.get(Q(id__icontains=snapshot_id))


### Tag #########################################################################

class TagSchema(Schema):
    TYPE: str = 'core.models.Tag'
    id: UUID
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
        User = get_user_model()
        return User.objects.get(id=obj.created_by_id).username

    @staticmethod
    def resolve_num_snapshots(obj, context):
        return obj.snapshot_set.all().distinct().count()

    @staticmethod
    def resolve_snapshots(obj, context):
        if context['request'].with_snapshots:
            return obj.snapshot_set.all().distinct()
        return Snapshot.objects.none()


@router.get("/tags", response=List[TagSchema], url_name="get_tags")
@paginate(CustomPagination)
def get_tags(request):
    request.with_snapshots = False
    request.with_archiveresults = False
    return Tag.objects.all().distinct()


@router.get("/tag/{tag_id}", response=TagSchema, url_name="get_tag")
def get_tag(request, tag_id: str, with_snapshots: bool = True):
    request.with_snapshots = with_snapshots
    request.with_archiveresults = False
    try:
        return Tag.objects.get(id__icontains=tag_id)
    except (Tag.DoesNotExist, ValidationError):
        return Tag.objects.get(slug__icontains=tag_id)


@router.get("/any/{id}", response=Union[SnapshotSchema, ArchiveResultSchema, TagSchema, CrawlSchema], url_name="get_any", summary="Get any object by its ID")
def get_any(request, id: str):
    """Get any object by its ID (e.g. snapshot, archiveresult, tag, crawl, etc.)."""
    request.with_snapshots = False
    request.with_archiveresults = False

    for getter in [get_snapshot, get_archiveresult, get_tag]:
        try:
            response = getter(request, id)
            if response:
                return redirect(f"/api/v1/{response._meta.app_label}/{response._meta.model_name}/{response.id}?{request.META['QUERY_STRING']}")
        except Exception:
            pass

    try:
        from archivebox.api.v1_crawls import get_crawl
        response = get_crawl(request, id)
        if response:
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
def tags_autocomplete(request, q: str = ""):
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
def tags_create(request, data: TagCreateSchema):
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
        tag = Tag.objects.filter(name__iexact=name).first()

    return {
        'success': True,
        'tag_id': tag.pk,
        'tag_name': tag.name,
        'created': created,
    }


@router.post("/tags/add-to-snapshot/", response=TagSnapshotResponseSchema, url_name="tags_add_to_snapshot")
def tags_add_to_snapshot(request, data: TagSnapshotRequestSchema):
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
        tag = Tag.objects.filter(name__iexact=name).first() or tag
    elif data.tag_id:
        try:
            tag = Tag.objects.get(pk=data.tag_id)
        except Tag.DoesNotExist:
            raise HttpError(404, 'Tag not found')
    else:
        raise HttpError(400, 'Either tag_name or tag_id is required')

    # Add the tag to the snapshot
    snapshot.tags.add(tag)

    return {
        'success': True,
        'tag_id': tag.pk,
        'tag_name': tag.name,
    }


@router.post("/tags/remove-from-snapshot/", response=TagSnapshotResponseSchema, url_name="tags_remove_from_snapshot")
def tags_remove_from_snapshot(request, data: TagSnapshotRequestSchema):
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
    snapshot.tags.remove(tag)

    return {
        'success': True,
        'tag_id': tag.pk,
        'tag_name': tag.name,
    }
