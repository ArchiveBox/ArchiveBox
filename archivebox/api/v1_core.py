__package__ = "archivebox.api"

import math
from collections import defaultdict
from uuid import UUID
from typing import Union, Any, Annotated
from datetime import datetime

from django.db.models import Model, Q, Sum
from django.db.models.functions import Coalesce
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.shortcuts import redirect
from django.utils import timezone

from ninja import Router, Schema, FilterLookup, FilterSchema, Query
from ninja.pagination import paginate, PaginationBase
from ninja.errors import HttpError

from archivebox.core.models import Snapshot, ArchiveResult, Tag
from archivebox.api.auth import auth_using_token
from archivebox.config.common import SERVER_CONFIG
from archivebox.core.tag_utils import (
    build_tag_cards,
    delete_tag as delete_tag_record,
    export_tag_snapshots_jsonl,
    export_tag_urls,
    get_matching_tags,
    get_or_create_tag,
    get_tag_by_ref,
    normalize_created_by_filter,
    normalize_created_year_filter,
    normalize_has_snapshots_filter,
    normalize_tag_sort,
    rename_tag as rename_tag_record,
)
from archivebox.crawls.models import Crawl
from archivebox.api.v1_crawls import CrawlSchema


router = Router(tags=["Core Models"])


class CustomPagination(PaginationBase):
    class Input(PaginationBase.Input):
        limit: int = 200
        offset: int = 0
        page: int = 0

    class Output(PaginationBase.Output):
        count: int
        total_items: int
        total_pages: int
        page: int
        limit: int
        offset: int
        num_items: int
        items: list[Any]

    def paginate_queryset(self, queryset, pagination: Input, request: HttpRequest, **params):
        limit = min(pagination.limit, 500)
        offset = pagination.offset or (pagination.page * limit)
        total = queryset.count()
        total_pages = math.ceil(total / limit)
        current_page = math.ceil(offset / (limit + 1))
        items = queryset[offset : offset + limit]
        return {
            "count": total,
            "total_items": total,
            "total_pages": total_pages,
            "page": current_page,
            "limit": limit,
            "offset": offset,
            "num_items": len(items),
            "items": items,
        }


### ArchiveResult #########################################################################


class MinimalArchiveResultSchema(Schema):
    TYPE: str = "core.models.ArchiveResult"
    id: UUID
    created_at: datetime | None
    modified_at: datetime | None
    created_by_id: str
    created_by_username: str
    status: str
    retry_at: datetime | None = None
    plugin: str
    hook_name: str
    process_id: UUID | None
    cmd_version: str | None
    cmd: list[str] | None
    pwd: str | None
    output_str: str
    output_json: dict[str, Any] | None
    output_files: dict[str, dict[str, Any]] | None
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

    @staticmethod
    def resolve_output_files(obj):
        return obj.output_file_map()

    @staticmethod
    def resolve_output_mimetypes(obj) -> str:
        mime_sizes: dict[str, int] = defaultdict(int)
        for metadata in obj.output_file_map().values():
            if not isinstance(metadata, dict):
                continue
            mimetype = str(metadata.get("mimetype") or "").strip()
            try:
                size = max(int(metadata.get("size") or 0), 0)
            except (TypeError, ValueError):
                size = 0
            if mimetype and size:
                mime_sizes[mimetype] += size
        if mime_sizes:
            return ",".join(mime for mime, _size in sorted(mime_sizes.items(), key=lambda item: item[1], reverse=True))
        return obj.output_mimetypes or ""


class ArchiveResultSchema(MinimalArchiveResultSchema):
    TYPE: str = "core.models.ArchiveResult"
    snapshot_id: UUID
    snapshot_timestamp: str
    snapshot_url: str
    snapshot_tags: list[str]

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
    id: Annotated[str | None, FilterLookup(["id__startswith", "snapshot__id__startswith", "snapshot__timestamp__startswith"])] = None
    search: Annotated[
        str | None,
        FilterLookup(
            [
                "snapshot__url__icontains",
                "snapshot__title__icontains",
                "snapshot__tags__name__icontains",
                "plugin",
                "output_str__icontains",
                "id__startswith",
                "snapshot__id__startswith",
                "snapshot__timestamp__startswith",
            ],
        ),
    ] = None
    snapshot_id: Annotated[str | None, FilterLookup(["snapshot__id__startswith", "snapshot__timestamp__startswith"])] = None
    snapshot_url: Annotated[str | None, FilterLookup("snapshot__url__icontains")] = None
    snapshot_tag: Annotated[str | None, FilterLookup("snapshot__tags__name__icontains")] = None
    status: Annotated[str | None, FilterLookup("status")] = None
    output_str: Annotated[str | None, FilterLookup("output_str__icontains")] = None
    plugin: Annotated[str | None, FilterLookup("plugin__icontains")] = None
    hook_name: Annotated[str | None, FilterLookup("hook_name__icontains")] = None
    process_id: Annotated[str | None, FilterLookup("process__id__startswith")] = None
    cmd: Annotated[str | None, FilterLookup("cmd__0__icontains")] = None
    pwd: Annotated[str | None, FilterLookup("pwd__icontains")] = None
    cmd_version: Annotated[str | None, FilterLookup("cmd_version")] = None
    created_at: Annotated[datetime | None, FilterLookup("created_at")] = None
    created_at__gte: Annotated[datetime | None, FilterLookup("created_at__gte")] = None
    created_at__lt: Annotated[datetime | None, FilterLookup("created_at__lt")] = None


@router.get("/archiveresults", response=list[ArchiveResultSchema], url_name="get_archiveresult")
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
    TYPE: str = "core.models.Snapshot"
    id: UUID
    created_by_id: str
    created_by_username: str
    created_at: datetime
    modified_at: datetime
    status: str
    retry_at: datetime | None
    bookmarked_at: datetime
    downloaded_at: datetime | None
    url: str
    tags: list[str]
    title: str | None
    timestamp: str
    archive_path: str
    archive_size: int
    output_size: int
    num_archiveresults: int
    archiveresults: list[MinimalArchiveResultSchema]

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
    def resolve_archive_size(obj):
        return int(getattr(obj, "output_size_sum", obj.archive_size) or 0)

    @staticmethod
    def resolve_output_size(obj):
        return SnapshotSchema.resolve_archive_size(obj)

    @staticmethod
    def resolve_num_archiveresults(obj, context):
        return obj.archiveresult_set.all().distinct().count()

    @staticmethod
    def resolve_archiveresults(obj, context):
        if bool(getattr(context["request"], "with_archiveresults", False)):
            return obj.archiveresult_set.all().distinct()
        return ArchiveResult.objects.none()


class SnapshotUpdateSchema(Schema):
    status: str | None = None
    retry_at: datetime | None = None
    tags: list[str] | None = None


class SnapshotCreateSchema(Schema):
    url: str
    crawl_id: str | None = None
    depth: int = 0
    title: str | None = None
    tags: list[str] | None = None
    status: str | None = None


class SnapshotDeleteResponseSchema(Schema):
    success: bool
    snapshot_id: str
    crawl_id: str
    deleted_count: int


class DeleteAllFailedSnapshotsResponseSchema(Schema):
    success: bool
    failed_snapshots_count: int
    deleted_count: int


def get_failed_snapshots():
    """Get all snapshots that have at least one failed ArchiveResult."""
    from archivebox.core.models import ArchiveResult

    failed_snapshot_ids = ArchiveResult.objects.filter(
        status=ArchiveResult.StatusChoices.FAILED
    ).values_list("snapshot_id", flat=True).distinct()

    return Snapshot.objects.filter(id__in=failed_snapshot_ids)


def normalize_tag_list(tags: list[str] | None = None) -> list[str]:
    return [tag.strip() for tag in (tags or []) if tag and tag.strip()]


class SnapshotFilterSchema(FilterSchema):
    id: Annotated[str | None, FilterLookup(["id__icontains", "timestamp__startswith"])] = None
    created_by_id: Annotated[str | None, FilterLookup("crawl__created_by_id")] = None
    created_by_username: Annotated[str | None, FilterLookup("crawl__created_by__username__icontains")] = None
    created_at__gte: Annotated[datetime | None, FilterLookup("created_at__gte")] = None
    created_at__lt: Annotated[datetime | None, FilterLookup("created_at__lt")] = None
    created_at: Annotated[datetime | None, FilterLookup("created_at")] = None
    modified_at: Annotated[datetime | None, FilterLookup("modified_at")] = None
    modified_at__gte: Annotated[datetime | None, FilterLookup("modified_at__gte")] = None
    modified_at__lt: Annotated[datetime | None, FilterLookup("modified_at__lt")] = None
    search: Annotated[
        str | None,
        FilterLookup(["url__icontains", "title__icontains", "tags__name__icontains", "id__icontains", "timestamp__startswith"]),
    ] = None
    url: Annotated[str | None, FilterLookup("url")] = None
    tag: Annotated[str | None, FilterLookup("tags__name")] = None
    title: Annotated[str | None, FilterLookup("title__icontains")] = None
    timestamp: Annotated[str | None, FilterLookup("timestamp__startswith")] = None
    bookmarked_at__gte: Annotated[datetime | None, FilterLookup("bookmarked_at__gte")] = None
    bookmarked_at__lt: Annotated[datetime | None, FilterLookup("bookmarked_at__lt")] = None


@router.get("/snapshots", response=list[SnapshotSchema], url_name="get_snapshots")
@paginate(CustomPagination)
def get_snapshots(request: HttpRequest, filters: Query[SnapshotFilterSchema], with_archiveresults: bool = False):
    """List all Snapshot entries matching these filters."""
    setattr(request, "with_archiveresults", with_archiveresults)
    queryset = Snapshot.objects.annotate(output_size_sum=Coalesce(Sum("archiveresult__output_size"), 0))
    return filters.filter(queryset).distinct()


@router.get("/snapshot/{snapshot_id}", response=SnapshotSchema, url_name="get_snapshot")
def get_snapshot(request: HttpRequest, snapshot_id: str, with_archiveresults: bool = True):
    """Get a specific Snapshot by id."""
    setattr(request, "with_archiveresults", with_archiveresults)
    queryset = Snapshot.objects.annotate(output_size_sum=Coalesce(Sum("archiveresult__output_size"), 0))
    try:
        return queryset.get(Q(id__startswith=snapshot_id) | Q(timestamp__startswith=snapshot_id))
    except Snapshot.DoesNotExist:
        return queryset.get(Q(id__icontains=snapshot_id))


@router.post("/snapshots", response=SnapshotSchema, url_name="create_snapshot")
def create_snapshot(request: HttpRequest, data: SnapshotCreateSchema):
    tags = normalize_tag_list(data.tags)
    if data.status is not None and data.status not in Snapshot.StatusChoices.values:
        raise HttpError(400, f"Invalid status: {data.status}")
    if not data.url.strip():
        raise HttpError(400, "URL is required")
    if data.depth not in (0, 1, 2, 3, 4):
        raise HttpError(400, "depth must be between 0 and 4")

    if data.crawl_id:
        crawl = Crawl.objects.get(id__icontains=data.crawl_id)
        crawl_tags = normalize_tag_list(crawl.tags_str.split(","))
        tags = tags or crawl_tags
    else:
        crawl = Crawl.objects.create(
            urls=data.url,
            max_depth=max(data.depth, 0),
            tags_str=",".join(tags),
            status=Crawl.StatusChoices.QUEUED,
            retry_at=timezone.now(),
            created_by=request.user if isinstance(request.user, User) else None,
        )

    snapshot_defaults = {
        "depth": data.depth,
        "title": data.title,
        "timestamp": str(timezone.now().timestamp()),
        "status": data.status or Snapshot.StatusChoices.QUEUED,
        "retry_at": timezone.now(),
    }
    snapshot, _ = Snapshot.objects.get_or_create(
        url=data.url,
        crawl=crawl,
        defaults=snapshot_defaults,
    )

    update_fields: list[str] = []
    if data.title is not None and snapshot.title != data.title:
        snapshot.title = data.title
        update_fields.append("title")
    if data.status is not None and snapshot.status != data.status:
        if data.status not in Snapshot.StatusChoices.values:
            raise HttpError(400, f"Invalid status: {data.status}")
        snapshot.status = data.status
        update_fields.append("status")
    if update_fields:
        update_fields.append("modified_at")
        snapshot.save(update_fields=update_fields)

    if tags:
        snapshot.save_tags(tags)

    try:
        snapshot.ensure_crawl_symlink()
    except Exception:
        pass

    setattr(request, "with_archiveresults", False)
    return snapshot


@router.patch("/snapshot/{snapshot_id}", response=SnapshotSchema, url_name="patch_snapshot")
def patch_snapshot(request: HttpRequest, snapshot_id: str, data: SnapshotUpdateSchema):
    """Update a snapshot (e.g., set status=sealed to cancel queued work)."""
    try:
        snapshot = Snapshot.objects.get(Q(id__startswith=snapshot_id) | Q(timestamp__startswith=snapshot_id))
    except Snapshot.DoesNotExist:
        snapshot = Snapshot.objects.get(Q(id__icontains=snapshot_id))

    payload = data.dict(exclude_unset=True)
    update_fields = ["modified_at"]
    tags = payload.pop("tags", None)

    if "status" in payload:
        if payload["status"] not in Snapshot.StatusChoices.values:
            raise HttpError(400, f"Invalid status: {payload['status']}")
        snapshot.status = payload["status"]
        if snapshot.status == Snapshot.StatusChoices.SEALED and "retry_at" not in payload:
            snapshot.retry_at = None
        update_fields.append("status")

    if "retry_at" in payload:
        snapshot.retry_at = payload["retry_at"]
        update_fields.append("retry_at")

    if tags is not None:
        snapshot.save_tags(normalize_tag_list(tags))

    snapshot.save(update_fields=update_fields)
    setattr(request, "with_archiveresults", False)
    return snapshot


@router.delete("/snapshot/{snapshot_id}", response=SnapshotDeleteResponseSchema, url_name="delete_snapshot")
def delete_snapshot(request: HttpRequest, snapshot_id: str):
    snapshot = get_snapshot(request, snapshot_id, with_archiveresults=False)
    snapshot_id_str = str(snapshot.id)
    crawl_id_str = str(snapshot.crawl.pk)
    deleted_count, _ = snapshot.delete()
    return {
        "success": True,
        "snapshot_id": snapshot_id_str,
        "crawl_id": crawl_id_str,
        "deleted_count": deleted_count,
    }


@router.delete("/snapshots/delete-all-failed", response=DeleteAllFailedSnapshotsResponseSchema, url_name="delete_all_failed_snapshots")
def delete_all_failed_snapshots(request: HttpRequest):
    """Delete all snapshots that have at least one failed ArchiveResult."""
    from django.db import transaction

    failed_snapshots = get_failed_snapshots()
    total = failed_snapshots.count()

    if total == 0:
        return {
            "success": True,
            "failed_snapshots_count": 0,
            "deleted_count": 0,
        }

    ids_to_delete = list(failed_snapshots.values_list("pk", flat=True))

    with transaction.atomic():
        deleted_count, _ = Snapshot.objects.filter(pk__in=ids_to_delete).delete()

    return {
        "success": True,
        "failed_snapshots_count": total,
        "deleted_count": deleted_count,
    }


@router.get("/snapshots/failed-count", response=dict, url_name="get_failed_snapshots_count")
def get_failed_snapshots_count(request: HttpRequest):
    """Get the count of snapshots that have at least one failed ArchiveResult."""
    failed_snapshots = get_failed_snapshots()
    return {
        "failed_snapshots_count": failed_snapshots.count(),
    }


### Tag #########################################################################


class TagSchema(Schema):
    TYPE: str = "core.models.Tag"
    id: int
    modified_at: datetime
    created_at: datetime
    created_by_id: str
    created_by_username: str
    name: str
    num_snapshots: int
    snapshots: list[SnapshotSchema]

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
    def resolve_num_snapshots(obj, context):
        return obj.snapshot_set.all().distinct().count()

    @staticmethod
    def resolve_snapshots(obj, context):
        if bool(getattr(context["request"], "with_snapshots", False)):
            return obj.snapshot_set.all().distinct()
        return Snapshot.objects.none()


@router.get("/tags", response=list[TagSchema], url_name="get_tags")
@paginate(CustomPagination)
def get_tags(request: HttpRequest):
    setattr(request, "with_snapshots", False)
    setattr(request, "with_archiveresults", False)
    return get_matching_tags()


@router.get("/tag/{tag_id}", response=TagSchema, url_name="get_tag")
def get_tag(request: HttpRequest, tag_id: str, with_snapshots: bool = True):
    setattr(request, "with_snapshots", with_snapshots)
    setattr(request, "with_archiveresults", False)
    try:
        return get_tag_by_ref(tag_id)
    except (Tag.DoesNotExist, ValidationError):
        raise HttpError(404, "Tag not found")


@router.get(
    "/any/{id}",
    response=Union[SnapshotSchema, ArchiveResultSchema, TagSchema, CrawlSchema],
    url_name="get_any",
    summary="Get any object by its ID",
)
def get_any(request: HttpRequest, id: str):
    """Get any object by its ID (e.g. snapshot, archiveresult, tag, crawl, etc.)."""
    setattr(request, "with_snapshots", False)
    setattr(request, "with_archiveresults", False)

    for getter in [get_snapshot, get_archiveresult, get_tag]:
        try:
            response = getter(request, id)
            if isinstance(response, Model):
                return redirect(
                    f"/api/v1/{response._meta.app_label}/{response._meta.model_name}/{response.pk}?{request.META['QUERY_STRING']}",
                )
        except Exception:
            pass

    try:
        from archivebox.api.v1_crawls import get_crawl

        response = get_crawl(request, id)
        if isinstance(response, Model):
            return redirect(f"/api/v1/{response._meta.app_label}/{response._meta.model_name}/{response.pk}?{request.META['QUERY_STRING']}")
    except Exception:
        pass

    raise HttpError(404, "Object with given ID not found")


### Tag Editor API Endpoints #########################################################################


class TagAutocompleteSchema(Schema):
    tags: list[dict]


class TagCreateSchema(Schema):
    name: str


class TagCreateResponseSchema(Schema):
    success: bool
    tag_id: int
    tag_name: str
    created: bool


class TagSearchSnapshotSchema(Schema):
    id: str
    title: str
    url: str
    favicon_url: str
    admin_url: str
    archive_url: str
    downloaded_at: str | None = None


class TagSearchCardSchema(Schema):
    id: int
    name: str
    slug: str
    num_snapshots: int
    filter_url: str
    edit_url: str
    export_urls_url: str
    export_jsonl_url: str
    rename_url: str
    delete_url: str
    snapshots: list[TagSearchSnapshotSchema]


class TagSearchResponseSchema(Schema):
    tags: list[TagSearchCardSchema]
    sort: str
    created_by: str
    year: str
    has_snapshots: str


class TagUpdateSchema(Schema):
    name: str


class TagUpdateResponseSchema(Schema):
    success: bool
    tag_id: int
    tag_name: str


class TagDeleteResponseSchema(Schema):
    success: bool
    tag_id: int
    deleted_count: int


class TagSnapshotRequestSchema(Schema):
    snapshot_id: str
    tag_name: str | None = None
    tag_id: int | None = None


class TagSnapshotResponseSchema(Schema):
    success: bool
    tag_id: int
    tag_name: str


@router.get("/tags/search/", response=TagSearchResponseSchema, url_name="search_tags")
def search_tags(
    request: HttpRequest,
    q: str = "",
    sort: str = "created_desc",
    created_by: str = "",
    year: str = "",
    has_snapshots: str = "all",
):
    """Return detailed tag cards for admin/live-search UIs."""
    normalized_sort = normalize_tag_sort(sort)
    normalized_created_by = normalize_created_by_filter(created_by)
    normalized_year = normalize_created_year_filter(year)
    normalized_has_snapshots = normalize_has_snapshots_filter(has_snapshots)
    return {
        "tags": build_tag_cards(
            query=q,
            request=request,
            sort=normalized_sort,
            created_by=normalized_created_by,
            year=normalized_year,
            has_snapshots=normalized_has_snapshots,
        ),
        "sort": normalized_sort,
        "created_by": normalized_created_by,
        "year": normalized_year,
        "has_snapshots": normalized_has_snapshots,
    }


def _public_tag_listing_enabled() -> bool:
    explicit = getattr(settings, "PUBLIC_SNAPSHOTS_LIST", None)
    if explicit is not None:
        return bool(explicit)
    return bool(getattr(settings, "PUBLIC_INDEX", SERVER_CONFIG.PUBLIC_INDEX))


def _request_has_tag_autocomplete_access(request: HttpRequest) -> bool:
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        return True

    token = request.GET.get("api_key") or request.headers.get("X-ArchiveBox-API-Key")
    auth_header = request.headers.get("Authorization", "")
    if not token and auth_header.lower().startswith("bearer "):
        token = auth_header.split(None, 1)[1].strip()

    if token and auth_using_token(token=token, request=request):
        return True

    return _public_tag_listing_enabled()


@router.get("/tags/autocomplete/", response=TagAutocompleteSchema, url_name="tags_autocomplete", auth=None)
def tags_autocomplete(request: HttpRequest, q: str = ""):
    """Return tags matching the query for autocomplete."""
    if not _request_has_tag_autocomplete_access(request):
        raise HttpError(401, "Authentication required")

    tags = get_matching_tags(q)[: 50 if not q else 20]

    return {
        "tags": [{"id": tag.pk, "name": tag.name, "num_snapshots": getattr(tag, "num_snapshots", 0)} for tag in tags],
    }


@router.post("/tags/create/", response=TagCreateResponseSchema, url_name="tags_create")
def tags_create(request: HttpRequest, data: TagCreateSchema):
    """Create a new tag or return existing one."""
    try:
        tag, created = get_or_create_tag(
            data.name,
            created_by=request.user if request.user.is_authenticated else None,
        )
    except ValueError as err:
        raise HttpError(400, str(err)) from err

    return {
        "success": True,
        "tag_id": tag.pk,
        "tag_name": tag.name,
        "created": created,
    }


@router.post("/tag/{tag_id}/rename", response=TagUpdateResponseSchema, url_name="rename_tag")
def rename_tag(request: HttpRequest, tag_id: int, data: TagUpdateSchema):
    try:
        tag = rename_tag_record(get_tag_by_ref(tag_id), data.name)
    except Tag.DoesNotExist as err:
        raise HttpError(404, "Tag not found") from err
    except ValueError as err:
        raise HttpError(400, str(err)) from err

    return {
        "success": True,
        "tag_id": tag.pk,
        "tag_name": tag.name,
    }


@router.delete("/tag/{tag_id}", response=TagDeleteResponseSchema, url_name="delete_tag")
def delete_tag(request: HttpRequest, tag_id: int):
    try:
        tag = get_tag_by_ref(tag_id)
    except Tag.DoesNotExist as err:
        raise HttpError(404, "Tag not found") from err

    deleted_count, _ = delete_tag_record(tag)
    return {
        "success": True,
        "tag_id": int(tag_id),
        "deleted_count": deleted_count,
    }


@router.get("/tag/{tag_id}/urls.txt", url_name="tag_urls_export")
def tag_urls_export(request: HttpRequest, tag_id: int):
    try:
        tag = get_tag_by_ref(tag_id)
    except Tag.DoesNotExist as err:
        raise HttpError(404, "Tag not found") from err

    response = HttpResponse(export_tag_urls(tag), content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="tag-{tag.slug}-urls.txt"'
    return response


@router.get("/tag/{tag_id}/snapshots.jsonl", url_name="tag_snapshots_export")
def tag_snapshots_export(request: HttpRequest, tag_id: int):
    try:
        tag = get_tag_by_ref(tag_id)
    except Tag.DoesNotExist as err:
        raise HttpError(404, "Tag not found") from err

    response = HttpResponse(export_tag_snapshots_jsonl(tag), content_type="application/x-ndjson; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="tag-{tag.slug}-snapshots.jsonl"'
    return response


@router.post("/tags/add-to-snapshot/", response=TagSnapshotResponseSchema, url_name="tags_add_to_snapshot")
def tags_add_to_snapshot(request: HttpRequest, data: TagSnapshotRequestSchema):
    """Add a tag to a snapshot. Creates the tag if it doesn't exist."""
    # Get the snapshot
    try:
        snapshot = Snapshot.objects.get(
            Q(id__startswith=data.snapshot_id) | Q(timestamp__startswith=data.snapshot_id),
        )
    except Snapshot.DoesNotExist:
        raise HttpError(404, "Snapshot not found")
    except Snapshot.MultipleObjectsReturned:
        snapshot = Snapshot.objects.filter(
            Q(id__startswith=data.snapshot_id) | Q(timestamp__startswith=data.snapshot_id),
        ).first()
        if snapshot is None:
            raise HttpError(404, "Snapshot not found")

    # Get or create the tag
    if data.tag_name:
        try:
            tag, _ = get_or_create_tag(
                data.tag_name,
                created_by=request.user if request.user.is_authenticated else None,
            )
        except ValueError as err:
            raise HttpError(400, str(err)) from err
    elif data.tag_id:
        try:
            tag = get_tag_by_ref(data.tag_id)
        except Tag.DoesNotExist:
            raise HttpError(404, "Tag not found")
    else:
        raise HttpError(400, "Either tag_name or tag_id is required")

    # Add the tag to the snapshot
    snapshot.tags.add(tag.pk)

    return {
        "success": True,
        "tag_id": tag.pk,
        "tag_name": tag.name,
    }


@router.post("/tags/remove-from-snapshot/", response=TagSnapshotResponseSchema, url_name="tags_remove_from_snapshot")
def tags_remove_from_snapshot(request: HttpRequest, data: TagSnapshotRequestSchema):
    """Remove a tag from a snapshot."""
    # Get the snapshot
    try:
        snapshot = Snapshot.objects.get(
            Q(id__startswith=data.snapshot_id) | Q(timestamp__startswith=data.snapshot_id),
        )
    except Snapshot.DoesNotExist:
        raise HttpError(404, "Snapshot not found")
    except Snapshot.MultipleObjectsReturned:
        snapshot = Snapshot.objects.filter(
            Q(id__startswith=data.snapshot_id) | Q(timestamp__startswith=data.snapshot_id),
        ).first()
        if snapshot is None:
            raise HttpError(404, "Snapshot not found")

    # Get the tag
    if data.tag_id:
        try:
            tag = Tag.objects.get(pk=data.tag_id)
        except Tag.DoesNotExist:
            raise HttpError(404, "Tag not found")
    elif data.tag_name:
        try:
            tag = Tag.objects.get(name__iexact=data.tag_name.strip())
        except Tag.DoesNotExist:
            raise HttpError(404, "Tag not found")
    else:
        raise HttpError(400, "Either tag_name or tag_id is required")

    # Remove the tag from the snapshot
    snapshot.tags.remove(tag.pk)

    return {
        "success": True,
        "tag_id": tag.pk,
        "tag_name": tag.name,
    }
