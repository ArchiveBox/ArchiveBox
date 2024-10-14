__package__ = 'archivebox.api'

import math
from uuid import UUID
from typing import List, Optional, Union, Any
from datetime import datetime

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from ninja import Router, Schema, FilterSchema, Field, Query
from ninja.pagination import paginate, PaginationBase
from ninja.errors import HttpError

from core.models import Snapshot, ArchiveResult, Tag
from api.models import APIToken, OutboundWebhook
from abid_utils.abid import ABID

from .auth import API_AUTH_METHODS

router = Router(tags=['Core Models'], auth=API_AUTH_METHODS)



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
    abid: str

    modified_at: datetime
    created_at: datetime
    created_by_id: str
    created_by_username: str

    extractor: str
    cmd_version: Optional[str]
    cmd: List[str]
    pwd: str
    status: str
    output: str

    start_ts: Optional[datetime]
    end_ts: Optional[datetime]

    @staticmethod
    def resolve_created_by_id(obj):
        return str(obj.created_by_id)
    
    @staticmethod
    def resolve_created_by_username(obj):
        User = get_user_model()
        return User.objects.get(id=obj.created_by_id).username

    @staticmethod
    def resolve_abid(obj):
        return str(obj.ABID)

    @staticmethod
    def resolve_created_at(obj):
        return obj.start_ts

    @staticmethod
    def resolve_snapshot_timestamp(obj):
        return obj.snapshot.timestamp
    
    @staticmethod
    def resolve_snapshot_url(obj):
        return obj.snapshot.url

    @staticmethod
    def resolve_snapshot_id(obj):
        return str(obj.snapshot_id)
    
    @staticmethod
    def resolve_snapshot_abid(obj):
        return str(obj.snapshot.ABID)

    @staticmethod
    def resolve_snapshot_tags(obj):
        return sorted(tag.name for tag in obj.snapshot.tags.all())

class ArchiveResultSchema(MinimalArchiveResultSchema):
    TYPE: str = 'core.models.ArchiveResult'

    # ... Extends MinimalArchiveResultSchema fields ...

    snapshot_id: UUID
    snapshot_abid: str
    snapshot_timestamp: str
    snapshot_url: str
    snapshot_tags: List[str]


class ArchiveResultFilterSchema(FilterSchema):
    id: Optional[str] = Field(None, q=['id__startswith', 'abid__icontains', 'snapshot__id__startswith', 'snapshot__abid__icontains', 'snapshot__timestamp__startswith'])

    search: Optional[str] = Field(None, q=['snapshot__url__icontains', 'snapshot__title__icontains', 'snapshot__tags__name__icontains', 'extractor', 'output__icontains', 'id__startswith', 'abid__icontains', 'snapshot__id__startswith', 'snapshot__abid__icontains', 'snapshot__timestamp__startswith'])
    snapshot_id: Optional[str] = Field(None, q=['snapshot__id__startswith', 'snapshot__abid__icontains', 'snapshot__timestamp__startswith'])
    snapshot_url: Optional[str] = Field(None, q='snapshot__url__icontains')
    snapshot_tag: Optional[str] = Field(None, q='snapshot__tags__name__icontains')
    
    status: Optional[str] = Field(None, q='status')
    output: Optional[str] = Field(None, q='output__icontains')
    extractor: Optional[str] = Field(None, q='extractor__icontains')
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
    qs = ArchiveResult.objects.all()
    results = filters.filter(qs).distinct()
    return results


@router.get("/archiveresult/{archiveresult_id}", response=ArchiveResultSchema, url_name="get_archiveresult")
def get_archiveresult(request, archiveresult_id: str):
    """Get a specific ArchiveResult by id or abid."""
    return ArchiveResult.objects.get(Q(id__icontains=archiveresult_id) | Q(abid__icontains=archiveresult_id))


# @router.post("/archiveresult", response=ArchiveResultSchema)
# def create_archiveresult(request, payload: ArchiveResultSchema):
#     archiveresult = ArchiveResult.objects.create(**payload.dict())
#     return archiveresult
#
# @router.put("/archiveresult/{archiveresult_id}", response=ArchiveResultSchema)
# def update_archiveresult(request, archiveresult_id: str, payload: ArchiveResultSchema):
#     archiveresult = get_object_or_404(ArchiveResult, id=archiveresult_id)
#   
#     for attr, value in payload.dict().items():
#         setattr(archiveresult, attr, value)
#     archiveresult.save()
#
#     return archiveresult
#
# @router.delete("/archiveresult/{archiveresult_id}")
# def delete_archiveresult(request, archiveresult_id: str):
#     archiveresult = get_object_or_404(ArchiveResult, id=archiveresult_id)
#     archiveresult.delete()
#     return {"success": True}





### Snapshot #########################################################################


class SnapshotSchema(Schema):
    TYPE: str = 'core.models.Snapshot'

    id: UUID
    abid: str

    created_by_id: str
    created_by_username: str
    created_at: datetime
    modified_at: datetime

    bookmarked_at: datetime
    downloaded_at: Optional[datetime]

    url: str
    tags: List[str]
    title: Optional[str]
    timestamp: str
    archive_path: str

    # url_for_admin: str
    # url_for_view: str

    num_archiveresults: int
    archiveresults: List[MinimalArchiveResultSchema]

    @staticmethod
    def resolve_created_by_id(obj):
        return str(obj.created_by_id)
    
    @staticmethod
    def resolve_created_by_username(obj):
        User = get_user_model()
        return User.objects.get(id=obj.created_by_id).username

    @staticmethod
    def resolve_abid(obj):
        return str(obj.ABID)

    @staticmethod
    def resolve_tags(obj):
        return sorted(tag.name for tag in obj.tags.all())

    # @staticmethod
    # def resolve_url_for_admin(obj):
    #     return f"/admin/core/snapshot/{obj.id}/change/"
    
    # @staticmethod
    # def resolve_url_for_view(obj):
    #     return f"/{obj.archive_path}"

    @staticmethod
    def resolve_num_archiveresults(obj, context):
        return obj.archiveresult_set.all().distinct().count()

    @staticmethod
    def resolve_archiveresults(obj, context):
        if context['request'].with_archiveresults:
            return obj.archiveresult_set.all().distinct()
        return ArchiveResult.objects.none()


class SnapshotFilterSchema(FilterSchema):
    id: Optional[str] = Field(None, q=['id__icontains', 'abid__icontains', 'timestamp__startswith'])
    abid: Optional[str] = Field(None, q='abid__icontains')

    created_by_id: str = Field(None, q='created_by_id')
    created_by_username: str = Field(None, q='created_by__username__icontains')

    created_at__gte: datetime = Field(None, q='created_at__gte')
    created_at__lt: datetime = Field(None, q='created_at__lt')
    created_at: datetime = Field(None, q='created_at')
    modified_at: datetime = Field(None, q='modified_at')
    modified_at__gte: datetime = Field(None, q='modified_at__gte')
    modified_at__lt: datetime = Field(None, q='modified_at__lt')

    search: Optional[str] = Field(None, q=['url__icontains', 'title__icontains', 'tags__name__icontains', 'id__icontains', 'abid__icontains', 'timestamp__startswith'])
    url: Optional[str] = Field(None, q='url')
    tag: Optional[str] = Field(None, q='tags__name')
    title: Optional[str] = Field(None, q='title__icontains')
    timestamp: Optional[str] = Field(None, q='timestamp__startswith')
    
    bookmarked_at__gte: Optional[datetime] = Field(None, q='bookmarked_at__gte')
    bookmarked_at__lt: Optional[datetime] = Field(None, q='bookmarked_at__lt')



@router.get("/snapshots", response=List[SnapshotSchema], url_name="get_snapshots")
@paginate(CustomPagination)
def get_snapshots(request, filters: SnapshotFilterSchema = Query(...), with_archiveresults: bool=False):
    """List all Snapshot entries matching these filters."""
    request.with_archiveresults = with_archiveresults

    qs = Snapshot.objects.all()
    results = filters.filter(qs).distinct()
    return results

@router.get("/snapshot/{snapshot_id}", response=SnapshotSchema, url_name="get_snapshot")
def get_snapshot(request, snapshot_id: str, with_archiveresults: bool=True):
    """Get a specific Snapshot by abid or id."""
    request.with_archiveresults = with_archiveresults
    snapshot = None
    try:
        snapshot = Snapshot.objects.get(Q(abid__startswith=snapshot_id) | Q(id__startswith=snapshot_id) | Q(timestamp__startswith=snapshot_id))
    except Snapshot.DoesNotExist:
        pass

    try:
        snapshot = snapshot or Snapshot.objects.get(Q(abid__icontains=snapshot_id) | Q(id__icontains=snapshot_id))
    except Snapshot.DoesNotExist:
        pass

    if not snapshot:
        raise Snapshot.DoesNotExist

    return snapshot


# @router.post("/snapshot", response=SnapshotSchema)
# def create_snapshot(request, payload: SnapshotSchema):
#     snapshot = Snapshot.objects.create(**payload.dict())
#     return snapshot
#
# @router.put("/snapshot/{snapshot_id}", response=SnapshotSchema)
# def update_snapshot(request, snapshot_id: str, payload: SnapshotSchema):
#     snapshot = get_object_or_404(Snapshot, id=snapshot_id)
#
#     for attr, value in payload.dict().items():
#         setattr(snapshot, attr, value)
#     snapshot.save()
#
#     return snapshot
#
# @router.delete("/snapshot/{snapshot_id}")
# def delete_snapshot(request, snapshot_id: str):
#     snapshot = get_object_or_404(Snapshot, id=snapshot_id)
#     snapshot.delete()
#     return {"success": True}



### Tag #########################################################################


class TagSchema(Schema):
    TYPE: str = 'core.models.Tag'

    id: UUID
    abid: str

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
def get_tag(request, tag_id: str, with_snapshots: bool=True):
    request.with_snapshots = with_snapshots
    request.with_archiveresults = False
    tag = None
    try:
        tag = Tag.objects.get(abid__icontains=tag_id)
    except (Tag.DoesNotExist, ValidationError):
        pass

    try:
        tag = tag or Tag.objects.get(id__icontains=tag_id)
    except (Tag.DoesNotExist, ValidationError):
        pass
    return tag



@router.get("/any/{abid}", response=Union[SnapshotSchema, ArchiveResultSchema, TagSchema], url_name="get_any")
def get_any(request, abid: str):
    request.with_snapshots = False
    request.with_archiveresults = False

    response = None
    try:
        response = response or get_snapshot(request, abid)
    except Exception:
        pass

    try:
        response = response or get_archiveresult(request, abid)
    except Exception:
        pass

    try:
        response = response or get_tag(request, abid)
    except Exception:
        pass

    if abid.startswith(APIToken.abid_prefix):
        raise HttpError(403, 'APIToken objects are not accessible via REST API')
    
    if abid.startswith(OutboundWebhook.abid_prefix):
        raise HttpError(403, 'OutboundWebhook objects are not accessible via REST API')

    raise HttpError(404, 'Object with given ABID not found')
