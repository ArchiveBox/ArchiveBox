__package__ = 'archivebox.api'

from uuid import UUID
from typing import List, Optional
from datetime import datetime

from django.db.models import Q
from django.shortcuts import get_object_or_404

from ninja import Router, Schema, FilterSchema, Field, Query
from ninja.pagination import paginate

from core.models import Snapshot, ArchiveResult, Tag
from abid_utils.abid import ABID

router = Router(tags=['Core Models'])




### ArchiveResult #########################################################################

class ArchiveResultSchema(Schema):
    abid: str
    uuid: UUID
    pk: str
    modified: datetime
    created: datetime
    created_by_id: str

    snapshot_abid: str
    snapshot_url: str
    snapshot_tags: str

    extractor: str
    cmd_version: str
    cmd: List[str]
    pwd: str
    status: str
    output: str

    @staticmethod
    def resolve_created_by_id(obj):
        return str(obj.created_by_id)

    @staticmethod
    def resolve_pk(obj):
        return str(obj.pk)

    @staticmethod
    def resolve_uuid(obj):
        return str(obj.uuid)

    @staticmethod
    def resolve_abid(obj):
        return str(obj.ABID)

    @staticmethod
    def resolve_created(obj):
        return obj.start_ts

    @staticmethod
    def resolve_snapshot_url(obj):
        return obj.snapshot.url

    @staticmethod
    def resolve_snapshot_abid(obj):
        return str(obj.snapshot.ABID)

    @staticmethod
    def resolve_snapshot_tags(obj):
        return obj.snapshot.tags_str()


class ArchiveResultFilterSchema(FilterSchema):
    uuid: Optional[UUID] = Field(None, q='uuid')
    # abid: Optional[str] = Field(None, q='abid')

    search: Optional[str] = Field(None, q=['snapshot__url__icontains', 'snapshot__title__icontains', 'snapshot__tags__name__icontains', 'extractor', 'output__icontains'])
    snapshot_uuid: Optional[UUID] = Field(None, q='snapshot_uuid__icontains')
    snapshot_url: Optional[str] = Field(None, q='snapshot__url__icontains')
    snapshot_tag: Optional[str] = Field(None, q='snapshot__tags__name__icontains')
    
    status: Optional[str] = Field(None, q='status')
    output: Optional[str] = Field(None, q='output__icontains')
    extractor: Optional[str] = Field(None, q='extractor__icontains')
    cmd: Optional[str] = Field(None, q='cmd__0__icontains')
    pwd: Optional[str] = Field(None, q='pwd__icontains')
    cmd_version: Optional[str] = Field(None, q='cmd_version')

    created: Optional[datetime] = Field(None, q='updated')
    created__gte: Optional[datetime] = Field(None, q='updated__gte')
    created__lt: Optional[datetime] = Field(None, q='updated__lt')


@router.get("/archiveresults", response=List[ArchiveResultSchema])
@paginate
def list_archiveresults(request, filters: ArchiveResultFilterSchema = Query(...)):
    """List all ArchiveResult entries matching these filters."""
    qs = ArchiveResult.objects.all()
    results = filters.filter(qs)
    return results


@router.get("/archiveresult/{archiveresult_id}", response=ArchiveResultSchema)
def get_archiveresult(request, archiveresult_id: str):
    """Get a specific ArchiveResult by abid, uuid, or pk."""
    return ArchiveResult.objects.get(Q(pk__icontains=archiveresult_id) | Q(abid__icontains=archiveresult_id) | Q(uuid__icontains=archiveresult_id))


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
    abid: str
    uuid: UUID
    pk: str
    modified: datetime
    created: datetime
    created_by_id: str

    url: str
    tags: str
    title: Optional[str]
    timestamp: str
    archive_path: str

    bookmarked: datetime
    added: datetime
    updated: Optional[datetime]

    num_archiveresults: int
    archiveresults: List[ArchiveResultSchema]

    @staticmethod
    def resolve_created_by_id(obj):
        return str(obj.created_by_id)

    @staticmethod
    def resolve_pk(obj):
        return str(obj.pk)

    @staticmethod
    def resolve_uuid(obj):
        return str(obj.uuid)

    @staticmethod
    def resolve_abid(obj):
        return str(obj.ABID)

    @staticmethod
    def resolve_tags(obj):
        return obj.tags_str()

    @staticmethod
    def resolve_num_archiveresults(obj, context):
        return obj.archiveresult_set.all().distinct().count()

    @staticmethod
    def resolve_archiveresults(obj, context):
        if context['request'].with_archiveresults:
            return obj.archiveresult_set.all().distinct()
        return ArchiveResult.objects.none()


class SnapshotFilterSchema(FilterSchema):
    abid: Optional[str] = Field(None, q='abid__icontains')
    uuid: Optional[str] = Field(None, q='uuid__icontains')
    pk: Optional[str] = Field(None, q='pk__icontains')
    created_by_id: str = Field(None, q='created_by_id__icontains')
    created__gte: datetime = Field(None, q='created__gte')
    created__lt: datetime = Field(None, q='created__lt')
    created: datetime = Field(None, q='created')
    modified: datetime = Field(None, q='modified')
    modified__gte: datetime = Field(None, q='modified__gte')
    modified__lt: datetime = Field(None, q='modified__lt')

    search: Optional[str] = Field(None, q=['url__icontains', 'title__icontains', 'tags__name__icontains', 'abid__icontains', 'uuid__icontains'])
    url: Optional[str] = Field(None, q='url')
    tag: Optional[str] = Field(None, q='tags__name')
    title: Optional[str] = Field(None, q='title__icontains')
    timestamp: Optional[str] = Field(None, q='timestamp__startswith')
    
    added__gte: Optional[datetime] = Field(None, q='added__gte')
    added__lt: Optional[datetime] = Field(None, q='added__lt')



@router.get("/snapshots", response=List[SnapshotSchema])
@paginate
def list_snapshots(request, filters: SnapshotFilterSchema = Query(...), with_archiveresults: bool=True):
    """List all Snapshot entries matching these filters."""
    request.with_archiveresults = with_archiveresults

    qs = Snapshot.objects.all()
    results = filters.filter(qs)
    return results

@router.get("/snapshot/{snapshot_id}", response=SnapshotSchema)
def get_snapshot(request, snapshot_id: str, with_archiveresults: bool=True):
    """Get a specific Snapshot by abid, uuid, or pk."""
    request.with_archiveresults = with_archiveresults
    snapshot = None
    try:
        snapshot = Snapshot.objects.get(Q(uuid__startswith=snapshot_id) | Q(abid__startswith=snapshot_id)| Q(pk__startswith=snapshot_id))
    except Snapshot.DoesNotExist:
        pass

    try:
        snapshot = snapshot or Snapshot.objects.get()
    except Snapshot.DoesNotExist:
        pass

    try:
        snapshot = snapshot or Snapshot.objects.get(Q(uuid__icontains=snapshot_id) | Q(abid__icontains=snapshot_id))
    except Snapshot.DoesNotExist:
        pass

    return snapshot


# @router.post("/snapshot", response=SnapshotSchema)
# def create_snapshot(request, payload: SnapshotSchema):
#     snapshot = Snapshot.objects.create(**payload.dict())
#     return snapshot
#
# @router.put("/snapshot/{snapshot_uuid}", response=SnapshotSchema)
# def update_snapshot(request, snapshot_uuid: str, payload: SnapshotSchema):
#     snapshot = get_object_or_404(Snapshot, uuid=snapshot_uuid)
#
#     for attr, value in payload.dict().items():
#         setattr(snapshot, attr, value)
#     snapshot.save()
#
#     return snapshot
#
# @router.delete("/snapshot/{snapshot_uuid}")
# def delete_snapshot(request, snapshot_uuid: str):
#     snapshot = get_object_or_404(Snapshot, uuid=snapshot_uuid)
#     snapshot.delete()
#     return {"success": True}



### Tag #########################################################################


class TagSchema(Schema):
    abid: Optional[UUID] = Field(None, q='abid')
    uuid: Optional[UUID] = Field(None, q='uuid')
    pk: Optional[UUID] = Field(None, q='pk')
    modified: datetime
    created: datetime
    created_by_id: str

    name: str
    slug: str


    @staticmethod
    def resolve_created_by_id(obj):
        return str(obj.created_by_id)

@router.get("/tags", response=List[TagSchema])
def list_tags(request):
    return Tag.objects.all()
