from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from ninja import Router
from ninja.errors import HttpError
from ninja.pagination import paginate

from archivebox.api.auth import authenticated_user_from_request
from archivebox.config.common import get_config
from archivebox.core.models import Snapshot, Tag
from archivebox.core.permissions import public_snapshots_queryset
from archivebox.core.tag_util import (
    add_snapshot_counts,
    build_tag_cards,
    export_tag_snapshots_jsonl,
    export_tag_urls,
    get_matching_tags,
    get_tag_by_ref,
    normalize_created_by_filter,
    normalize_created_year_filter,
    normalize_has_snapshots_filter,
    normalize_tag_sort,
)

from .pagination import CustomPagination
from .schemas import (
    TagAutocompleteSchema,
    TagCreateResponseSchema,
    TagCreateSchema,
    TagDeleteResponseSchema,
    TagSchema,
    TagSearchResponseSchema,
    TagSnapshotRequestSchema,
    TagSnapshotResponseSchema,
    TagUpdateResponseSchema,
    TagUpdateSchema,
)

router = Router(tags=["Core Models"])


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


def _get_snapshot_for_tag_edit(snapshot_ref: str) -> Snapshot:
    snapshot_ref = str(snapshot_ref or "").strip().lower()
    if not snapshot_ref:
        raise HttpError(400, "Snapshot id is required")

    snapshot_qs = Snapshot.objects.only("id")
    is_full_uuid = len(snapshot_ref.replace("-", "")) == 32 and all(char in "0123456789abcdef-" for char in snapshot_ref)
    if is_full_uuid:
        try:
            return snapshot_qs.get(pk=snapshot_ref.replace("-", ""))
        except (Snapshot.DoesNotExist, ValueError):
            pass

    if len(snapshot_ref) >= 14:
        try:
            return snapshot_qs.get(timestamp=snapshot_ref)
        except Snapshot.DoesNotExist:
            pass
        except Snapshot.MultipleObjectsReturned:
            snapshot = snapshot_qs.filter(timestamp=snapshot_ref).first()
            if snapshot is not None:
                return snapshot

    try:
        return snapshot_qs.get(Q(id__startswith=snapshot_ref) | Q(timestamp__startswith=snapshot_ref))
    except Snapshot.DoesNotExist:
        raise HttpError(404, "Snapshot not found") from None
    except Snapshot.MultipleObjectsReturned:
        snapshot = snapshot_qs.filter(Q(id__startswith=snapshot_ref) | Q(timestamp__startswith=snapshot_ref)).first()
        if snapshot is None:
            raise HttpError(404, "Snapshot not found")
        return snapshot


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
            preview_limit=0,
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
    return get_config().PUBLIC_INDEX


def _request_has_tag_autocomplete_access(request: HttpRequest) -> bool:
    if authenticated_user_from_request(request):
        return True

    return _public_tag_listing_enabled()


@router.get("/tags/autocomplete/", response=TagAutocompleteSchema, url_name="tags_autocomplete", auth=None)
def tags_autocomplete(request: HttpRequest, q: str = ""):
    """Return tags matching the query for autocomplete."""
    if not _request_has_tag_autocomplete_access(request):
        raise HttpError(401, "Authentication required")

    public_only = not request.user.is_authenticated and not request.__dict__.get("_api_token")
    queryset = get_matching_tags(q)
    public_snapshots = public_snapshots_queryset(Snapshot.objects.all())
    if public_only:
        queryset = queryset.filter(snapshot_set__id__in=public_snapshots.values("id")).distinct()
    tags = list(queryset[: 50 if not q else 20])
    add_snapshot_counts(tags, snapshot_queryset=public_snapshots if public_only else None)

    return {
        "tags": [{"id": tag.pk, "name": tag.name, "num_snapshots": tag.__dict__.get("num_snapshots", 0)} for tag in tags],
    }


@router.post("/tags/create/", response=TagCreateResponseSchema, url_name="tags_create")
def tags_create(request: HttpRequest, data: TagCreateSchema):
    """Create a new tag or return existing one."""
    try:
        tag, created = Tag.get_or_create_by_name(
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
        tag = get_tag_by_ref(tag_id).rename(data.name)
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

    deleted_count, _ = tag.delete()
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
    snapshot = _get_snapshot_for_tag_edit(data.snapshot_id)

    # Get or create the tag
    if data.tag_name:
        try:
            tag, _ = Tag.get_or_create_by_name(
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

    snapshot.add_tag_ids([tag.pk])

    return {
        "success": True,
        "tag_id": tag.pk,
        "tag_name": tag.name,
    }


@router.post("/tags/remove-from-snapshot/", response=TagSnapshotResponseSchema, url_name="tags_remove_from_snapshot")
def tags_remove_from_snapshot(request: HttpRequest, data: TagSnapshotRequestSchema):
    """Remove a tag from a snapshot."""
    snapshot = _get_snapshot_for_tag_edit(data.snapshot_id)

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

    snapshot.remove_tag_ids([tag.pk])

    return {
        "success": True,
        "tag_id": tag.pk,
        "tag_name": tag.name,
    }
