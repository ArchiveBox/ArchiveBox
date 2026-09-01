__package__ = "archivebox.api"

import math
import json
import mimetypes
import re
from html import unescape
from collections import defaultdict
from pathlib import Path, PurePosixPath
from uuid import UUID
from typing import Union, Any, Annotated
from datetime import datetime, time

from django.db import IntegrityError
from django.db.models import Model, Q
from django.http import HttpRequest, HttpResponse
from django.http.multipartparser import MultiPartParser, MultiPartParserError
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.feedgenerator import Rss201rev2Feed

from ninja import Router, Schema, FilterLookup, FilterSchema, Query, Form, UploadedFile
from ninja.pagination import paginate, PaginationBase
from ninja.errors import HttpError

from archivebox.core.models import Snapshot, ArchiveResult, Tag
from archivebox.core.permissions import public_snapshots_queryset
from archivebox.api.auth import authenticated_user_from_request
from archivebox.config.common import get_config
from archivebox.core.routes_util import build_web_url
from archivebox.misc.util import filter_queryset_by_uuid_substring, validate_url_length
from archivebox.core.tag_util import (
    add_snapshot_counts,
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
from archivebox.crawls.locks import crawl_lifecycle_lock
from archivebox.api.v1_crawls import CrawlSchema, get_crawl_by_ref
from archivebox.search.config import get_search_mode, get_search_mode_backend
from archivebox.search.query import apply_snapshot_search
from archivebox.core.snapshot_status import filter_snapshots_by_status, normalize_snapshot_status


router = Router(tags=["Core Models"])

ARCHIVERESULT_UPLOAD_HOOK_NAME = Snapshot.BROWSER_EXTENSION_UPLOAD_HOOK_NAME
ARCHIVERESULT_UPLOAD_PLUGIN_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


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
        total = queryset.values("pk").distinct().count() if queryset.query.distinct else queryset.count()
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
    queryset = filters.filter(ArchiveResult.objects.all())
    if filters.search or filters.snapshot_tag:
        return queryset.distinct()
    return queryset


def _uuid_ref_query(field_name: str, ref: str) -> Q:
    raw_ref = str(ref or "").strip()
    query = Q(**{f"{field_name}__startswith": raw_ref})
    if raw_ref:
        query |= Q(**{f"{field_name}__icontains": raw_ref})
    try:
        parsed_uuid = UUID(raw_ref)
    except (TypeError, ValueError):
        normalized_ref = raw_ref.replace("-", "")
        if normalized_ref and normalized_ref != raw_ref:
            query |= Q(**{f"{field_name}__startswith": normalized_ref})
            query |= Q(**{f"{field_name}__icontains": normalized_ref})
    else:
        query |= Q(**{field_name: parsed_uuid})
        query |= Q(**{f"{field_name}__startswith": parsed_uuid.hex})
    return query


@router.get("/archiveresult/{archiveresult_id}", response=ArchiveResultSchema, url_name="get_archiveresult")
def get_archiveresult(request: HttpRequest, archiveresult_id: str):
    """Get a specific ArchiveResult by id."""
    return ArchiveResult.objects.get(_uuid_ref_query("id", archiveresult_id))


def _normalize_uploaded_archiveresult_plugin(plugin: str) -> str:
    normalized = str(plugin or "").strip().strip("/")
    if not ARCHIVERESULT_UPLOAD_PLUGIN_RE.fullmatch(normalized):
        raise HttpError(400, "Invalid ArchiveResult plugin name")
    return normalized


def _normalize_uploaded_archiveresult_output_path(output_path: str, *, filename: str) -> str:
    raw_path = str(output_path or filename or "").strip().replace("\\", "/")
    if not raw_path:
        raise HttpError(400, "ArchiveResult output path is required")

    path = PurePosixPath(raw_path)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise HttpError(400, "Invalid ArchiveResult output path")

    return str(path)


def _parse_archiveresult_output_json(output_json: str | None) -> dict[str, Any] | None:
    if not output_json:
        return None
    try:
        parsed = json.loads(output_json)
    except json.JSONDecodeError as err:
        raise HttpError(400, "ArchiveResult output_json must be valid JSON") from err
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise HttpError(400, "ArchiveResult output_json must be a JSON object")
    return parsed


def _get_archiveresult_upload_data(request: HttpRequest):
    cached = request.__dict__.get("_archiveresult_upload_data")
    if cached is not None:
        return cached

    if request.method.upper() == "PATCH" and request.content_type.startswith("multipart/"):
        try:
            data = MultiPartParser(request.META, request, request.upload_handlers, request.encoding).parse()
        except MultiPartParserError as err:
            raise HttpError(400, f"Invalid ArchiveResult multipart upload: {err}") from err
    else:
        data = (request.POST, request.FILES)

    setattr(request, "_archiveresult_upload_data", data)
    return data


def _get_archiveresult_upload_files(request: HttpRequest, *, allow_empty: bool = False) -> list[UploadedFile]:
    _post, request_files = _get_archiveresult_upload_data(request)
    files = [*request_files.getlist("files"), *request_files.getlist("file")]
    if not files and not allow_empty:
        raise HttpError(400, "At least one ArchiveResult file is required")
    return files


def _get_archiveresult_upload_form_values(request: HttpRequest, *field_names: str) -> list[str]:
    request_post, _files = _get_archiveresult_upload_data(request)
    values: list[str] = []
    for field_name in field_names:
        values.extend(str(value) for value in request_post.getlist(field_name))
    if len(values) == 1:
        value = values[0].strip()
        if value.startswith("["):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
    return values


def _get_archiveresult_upload_form_value(request: HttpRequest, *field_names: str) -> str:
    request_post, _files = _get_archiveresult_upload_data(request)
    for field_name in field_names:
        value = request_post.get(field_name)
        if value is not None:
            return str(value)
    return ""


def _parse_archiveresult_upload_int(value: str, field_name: str, *, default: int | None = None) -> int:
    if value == "" and default is not None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as err:
        raise HttpError(400, f"ArchiveResult {field_name} must be an integer") from err
    if parsed < 0:
        raise HttpError(400, f"ArchiveResult {field_name} must be non-negative")
    return parsed


def _summarize_archiveresult_output_files(output_files: dict[str, dict[str, Any]]) -> tuple[int, str]:
    from abx_dl.output_files import OutputManifest

    manifest = OutputManifest.from_value(output_files)
    return manifest.total_size, ",".join(manifest.mimetypes)


def _get_snapshot_by_ref(snapshot_id: str):
    queryset = Snapshot.objects.select_related("crawl__created_by")
    try:
        return queryset.get(_uuid_ref_query("id", snapshot_id) | Q(timestamp__startswith=snapshot_id))
    except Snapshot.DoesNotExist:
        return queryset.get(_uuid_ref_query("id", snapshot_id))


def _queue_archiveresult_snapshot_maintenance(snapshot: Snapshot) -> None:
    """
    Mark an uploaded ArchiveResult's Snapshot as dirty without finalizing it.

    Upload API handlers are allowed to persist files and ArchiveResult rows, but
    Snapshot save() side effects, sealing, symlink creation, and index/details
    rewrites belong to the runner. retry_at is the scheduler signal the runner
    already watches, so only bump rows that are final or otherwise invisible.
    """
    # ArchiveResult.save() updates parent snapshot health/mtime before this
    # helper runs. Re-read the scheduler columns so the short CAS update below
    # does not lose to our own earlier ArchiveResult write.
    snapshot = Snapshot.objects.only("id", "status", "retry_at", "downloaded_at", "modified_at").get(id=snapshot.id)
    now = timezone.now()
    updates = {"modified_at": now}
    if snapshot.downloaded_at is None:
        updates["downloaded_at"] = now
    if snapshot.status == Snapshot.StatusChoices.SEALED or snapshot.retry_at is None:
        updates["retry_at"] = now
    snapshot.safe_update(updates, refresh=False)


def _write_archiveresult_files(
    request: HttpRequest,
    snapshot: Snapshot,
    plugin_name: str,
    *,
    existing_output_files: dict[str, dict[str, Any]] | None = None,
    allow_empty: bool = False,
) -> dict[str, dict[str, Any]]:
    files = _get_archiveresult_upload_files(request, allow_empty=allow_empty)
    output_paths = _get_archiveresult_upload_form_values(request, "output_paths", "output_path")
    mime_types = _get_archiveresult_upload_form_values(request, "mime_types", "mime_type")
    chunk_output_path = _get_archiveresult_upload_form_value(request, "chunk_output_path")

    snapshot_dir = snapshot.output_dir
    plugin_dir = snapshot_dir / plugin_name
    storage = FileSystemStorage(location=str(plugin_dir))
    output_files = dict(existing_output_files or {})

    if not files:
        return output_files

    if chunk_output_path:
        if len(files) != 1:
            raise HttpError(400, "Exactly one ArchiveResult file chunk is required")

        uploaded_file = files[0]
        relative_output_path = _normalize_uploaded_archiveresult_output_path(
            chunk_output_path,
            filename=uploaded_file.name,
        )
        chunk_index = _parse_archiveresult_upload_int(
            _get_archiveresult_upload_form_value(request, "chunk_index"),
            "chunk_index",
        )
        chunk_count = _parse_archiveresult_upload_int(
            _get_archiveresult_upload_form_value(request, "chunk_count"),
            "chunk_count",
        )
        chunk_offset = _parse_archiveresult_upload_int(
            _get_archiveresult_upload_form_value(request, "chunk_offset"),
            "chunk_offset",
        )
        chunk_total_size = _parse_archiveresult_upload_int(
            _get_archiveresult_upload_form_value(request, "chunk_total_size"),
            "chunk_total_size",
        )

        if chunk_count < 1:
            raise HttpError(400, "ArchiveResult chunk_count must be at least 1")
        if chunk_index >= chunk_count:
            raise HttpError(400, "ArchiveResult chunk_index must be less than chunk_count")
        if chunk_total_size and chunk_offset > chunk_total_size:
            raise HttpError(400, "ArchiveResult chunk_offset cannot exceed chunk_total_size")

        if chunk_index == 0 and chunk_offset == 0 and storage.exists(relative_output_path):
            storage.delete(relative_output_path)

        current_size = storage.size(relative_output_path) if storage.exists(relative_output_path) else 0
        if current_size != chunk_offset:
            raise HttpError(
                409,
                f"ArchiveResult chunk offset mismatch for {relative_output_path}: expected {current_size}, got {chunk_offset}",
            )

        Path(storage.path(relative_output_path)).parent.mkdir(parents=True, exist_ok=True)
        with storage.open(relative_output_path, "ab") as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        size = storage.size(relative_output_path)
        upload_complete = chunk_index + 1 == chunk_count
        if upload_complete and size != chunk_total_size:
            raise HttpError(
                409,
                f"ArchiveResult chunk size mismatch for {relative_output_path}: expected {chunk_total_size}, got {size}",
            )

        guessed_mime = mimetypes.guess_type(relative_output_path)[0]
        output_mime_type = (mime_types[0] if mime_types else "") or uploaded_file.content_type or guessed_mime or "application/octet-stream"
        output_files[relative_output_path] = {
            "extension": PurePosixPath(relative_output_path).suffix.lower().lstrip("."),
            "mimetype": output_mime_type,
            "size": size,
            "upload": {
                "chunked": True,
                "chunk_index": chunk_index,
                "chunk_count": chunk_count,
                "chunks_received": chunk_index + 1,
                "complete": upload_complete,
            },
        }

        return output_files

    for index, uploaded_file in enumerate(files):
        relative_output_path = _normalize_uploaded_archiveresult_output_path(
            output_paths[index] if index < len(output_paths) else "",
            filename=uploaded_file.name,
        )
        if storage.exists(relative_output_path):
            storage.delete(relative_output_path)
        saved_output_path = storage.save(relative_output_path, uploaded_file)
        size = storage.size(saved_output_path)
        guessed_mime = mimetypes.guess_type(saved_output_path)[0]
        output_mime_type = (
            (mime_types[index] if index < len(mime_types) else "")
            or uploaded_file.content_type
            or guessed_mime
            or "application/octet-stream"
        )
        output_files[saved_output_path] = {
            "extension": PurePosixPath(saved_output_path).suffix.lower().lstrip("."),
            "mimetype": output_mime_type,
            "size": size,
        }

    return output_files


@router.post(
    "/archiveresults",
    response=ArchiveResultSchema,
    url_name="create_archiveresult",
)
def create_archiveresult(
    request: HttpRequest,
    snapshot_id: str = Form(...),
    plugin: str = Form(...),
    output_str: str = Form(""),
    hook_name: str = Form(ARCHIVERESULT_UPLOAD_HOOK_NAME),
    status: str = Form(str(ArchiveResult.StatusChoices.SUCCEEDED)),
    output_json: str = Form(""),
):
    """Create or update an ArchiveResult with one or more output files."""
    snapshot = _get_snapshot_by_ref(snapshot_id)
    plugin_name = _normalize_uploaded_archiveresult_plugin(plugin)
    normalized_status = ArchiveResult.normalize_status(status)
    parsed_output_json = _parse_archiveresult_output_json(output_json)
    hook = hook_name or ARCHIVERESULT_UPLOAD_HOOK_NAME
    result_lookup = {
        "snapshot": snapshot,
        "plugin": plugin_name,
        "hook_name": hook,
    }
    uploaded_output_files = _write_archiveresult_files(
        request,
        snapshot,
        plugin_name,
        allow_empty=True,
    )
    result = ArchiveResult.objects.filter(**result_lookup).first()
    for _attempt in range(3):
        output_files = {
            **(result.output_file_map() if result else {}),
            **uploaded_output_files,
        }
        output_size, output_mimetypes = _summarize_archiveresult_output_files(output_files)
        output_file_paths = list(output_files.keys())
        result_status = normalized_status
        if result and result_status == ArchiveResult.StatusChoices.STARTED and result.status != ArchiveResult.StatusChoices.STARTED:
            result_status = result.status
        now = timezone.now()
        values = {
            "status": result_status,
            "output_str": output_str or (output_file_paths[0] if output_file_paths else ""),
            "output_json": parsed_output_json,
            "output_files": output_files,
            "output_size": output_size,
            "output_mimetypes": output_mimetypes,
            "start_ts": result.start_ts or now if result else now,
            "end_ts": now,
        }
        if result:
            if result.safe_update(values):
                break
            continue
        result, created = ArchiveResult.get_or_create_by_hook(
            snapshot,
            plugin_name,
            hook,
            defaults=values,
        )
        if created:
            break
    else:
        raise HttpError(409, "ArchiveResult changed while upload metadata was being updated")

    if result.status != ArchiveResult.StatusChoices.STARTED:
        _queue_archiveresult_snapshot_maintenance(snapshot)
    return result


@router.patch("/archiveresult/{archiveresult_id}", response=ArchiveResultSchema, url_name="patch_archiveresult")
def patch_archiveresult(
    request: HttpRequest,
    archiveresult_id: str,
):
    """Append or replace files on an existing ArchiveResult."""
    result = ArchiveResult.objects.select_related("snapshot__crawl__created_by").get(_uuid_ref_query("id", archiveresult_id))
    uploaded_output_files = _write_archiveresult_files(
        request,
        result.snapshot,
        result.plugin,
    )
    output_str = _get_archiveresult_upload_form_value(request, "output_str")
    status = _get_archiveresult_upload_form_value(request, "status")
    output_json = _get_archiveresult_upload_form_value(request, "output_json")
    parsed_output_json = _parse_archiveresult_output_json(output_json) if output_json else None

    if not ArchiveResult.output_files_upload_complete(uploaded_output_files):
        result.output_files = {**result.output_file_map(), **uploaded_output_files}
        result.output_size, result.output_mimetypes = _summarize_archiveresult_output_files(result.output_files)
        return result

    for _attempt in range(3):
        output_files = {**result.output_file_map(), **uploaded_output_files}
        output_size, output_mimetypes = _summarize_archiveresult_output_files(output_files)
        values: dict[str, Any] = {
            "output_files": output_files,
            "output_size": output_size,
            "output_mimetypes": output_mimetypes,
            "end_ts": timezone.now(),
        }
        if output_str:
            values["output_str"] = output_str
        if status:
            normalized_status = ArchiveResult.normalize_status(status)
            if normalized_status == ArchiveResult.StatusChoices.STARTED and result.status != ArchiveResult.StatusChoices.STARTED:
                normalized_status = result.status
            values["status"] = normalized_status
        elif result.status == ArchiveResult.StatusChoices.QUEUED:
            values["status"] = ArchiveResult.StatusChoices.SUCCEEDED
        if output_json:
            values["output_json"] = parsed_output_json
        if result.safe_update(values):
            break
    else:
        raise HttpError(409, "ArchiveResult changed while upload metadata was being updated")

    if result.status != ArchiveResult.StatusChoices.STARTED:
        _queue_archiveresult_snapshot_maintenance(result.snapshot)

    return result


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
        return int(obj.archive_size or 0)

    @staticmethod
    def resolve_output_size(obj):
        return SnapshotSchema.resolve_archive_size(obj)

    @staticmethod
    def resolve_num_archiveresults(obj, context):
        return obj.archiveresult_set.all().distinct().count()

    @staticmethod
    def resolve_archiveresults(obj, context):
        if bool(context["request"].__dict__.get("with_archiveresults", False)):
            return obj.archiveresult_set.all().distinct()
        return ArchiveResult.objects.none()


class SnapshotUpdateSchema(Schema):
    action: str | None = None
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


def normalize_tag_list(tags: list[str] | None = None) -> list[str]:
    return [tag.strip() for tag in (tags or []) if tag and tag.strip()]


def _parse_rss_before(before: str | None) -> datetime:
    if not before:
        return timezone.now()

    value = before.strip()
    parsed_dt = None

    if len(value) == 8 and value.isdigit():
        parsed_date = datetime.strptime(value, "%Y%m%d").date()
    else:
        parsed_dt = parse_datetime(value)
        parsed_date = None if parsed_dt else parse_date(value)

    if parsed_dt is None:
        if parsed_date is None:
            raise HttpError(400, "before must be an ISO datetime, YYYY-MM-DD, or YYYYMMDD")
        parsed_dt = datetime.combine(parsed_date, time.max)

    if timezone.is_naive(parsed_dt):
        parsed_dt = timezone.make_aware(parsed_dt, timezone.get_current_timezone())
    return parsed_dt


def _filter_snapshots_for_rss(
    *,
    crawl_id: str = "",
    created_by: str = "",
    before: str | None = None,
    limit: int = 50,
):
    limit = max(1, min(int(limit or 50), 500))
    before_dt = _parse_rss_before(before)
    queryset = (
        Snapshot.objects.select_related("crawl__created_by")
        .prefetch_related("tags")
        .only(
            "id",
            "url",
            "title",
            "timestamp",
            "bookmarked_at",
            "created_at",
            "modified_at",
            "fs_version",
            "crawl_id",
            "crawl__id",
            "crawl__created_by_id",
            "crawl__created_by__id",
            "crawl__created_by__username",
        )
        .filter(bookmarked_at__lte=before_dt)
    )
    crawl_id = crawl_id.strip()
    if crawl_id:
        matching_crawl_pks = list(filter_queryset_by_uuid_substring(Crawl.objects.all(), crawl_id).values_list("pk", flat=True)[:100])
        queryset = queryset.filter(crawl_id__in=matching_crawl_pks)

    created_by = created_by.strip()
    if created_by:
        created_by_query = Q(crawl__created_by__username__iexact=created_by)
        user_model = get_user_model()
        try:
            prepared_pk = user_model._meta.pk.get_prep_value(created_by)
        except (TypeError, ValueError, ValidationError):
            prepared_pk = None
        if prepared_pk not in (None, ""):
            created_by_query |= Q(crawl__created_by_id=prepared_pk)
        queryset = queryset.filter(created_by_query)

    return queryset.order_by("-bookmarked_at", "-created_at", "-id")[:limit]


def _snapshots_rss_response(
    request: HttpRequest,
    *,
    snapshots,
    title: str = "ArchiveBox Snapshots",
) -> HttpResponse:
    web_base_url = build_web_url("/", request=request).rstrip("/")
    feed_query = request.GET.copy()
    for sensitive_param in ("api_key", "token", "password"):
        feed_query.pop(sensitive_param, None)
    feed_path = request.path
    feed_url = request.build_absolute_uri(f"{feed_path}?{feed_query.urlencode()}" if feed_query else feed_path)

    feed = Rss201rev2Feed(
        title=title,
        link=build_web_url("/public/", request=request),
        description="Recently added ArchiveBox snapshots.",
        language="en",
        feed_url=feed_url,
    )

    for snapshot in snapshots:
        archived_url = build_web_url(f"/{snapshot.archive_path_from_db}", request=request)
        tags = [tag.name for tag in snapshot.tags.all()]
        crawl_user = snapshot.crawl.created_by if snapshot.crawl_id else None
        description = f"Original URL: {snapshot.url}\nArchived snapshot: {archived_url}"
        feed.add_item(
            title=unescape(snapshot.title or snapshot.url),
            link=archived_url or web_base_url,
            description=description,
            unique_id=str(snapshot.id),
            unique_id_is_permalink=False,
            pubdate=snapshot.bookmarked_at or snapshot.created_at,
            updateddate=snapshot.modified_at,
            author_name=crawl_user.username if crawl_user else None,
            categories=tags,
        )

    return HttpResponse(feed.writeString("utf-8"), content_type="application/rss+xml; charset=utf-8")


class SnapshotFilterSchema(FilterSchema):
    id: Annotated[str | None, FilterLookup(["id__istartswith", "id__iendswith", "timestamp__startswith"])] = None
    created_by_id: Annotated[str | None, FilterLookup("crawl__created_by_id")] = None
    created_by_username: Annotated[str | None, FilterLookup("crawl__created_by__username__icontains")] = None
    created_at__gte: Annotated[datetime | None, FilterLookup("created_at__gte")] = None
    created_at__lt: Annotated[datetime | None, FilterLookup("created_at__lt")] = None
    created_at: Annotated[datetime | None, FilterLookup("created_at")] = None
    modified_at: Annotated[datetime | None, FilterLookup("modified_at")] = None
    modified_at__gte: Annotated[datetime | None, FilterLookup("modified_at__gte")] = None
    modified_at__lt: Annotated[datetime | None, FilterLookup("modified_at__lt")] = None
    search: str | None = None
    search_mode: str | None = None
    status: str | None = None
    url: Annotated[str | None, FilterLookup("url")] = None
    tag: Annotated[str | None, FilterLookup("tags__name")] = None
    title: Annotated[str | None, FilterLookup("title__icontains")] = None
    timestamp: Annotated[str | None, FilterLookup("timestamp__startswith")] = None
    bookmarked_at__gte: Annotated[datetime | None, FilterLookup("bookmarked_at__gte")] = None
    bookmarked_at__lt: Annotated[datetime | None, FilterLookup("bookmarked_at__lt")] = None

    def filter_search(self, value: str | None) -> Q:
        return Q()

    def filter_search_mode(self, value: str | None) -> Q:
        return Q()

    def filter_status(self, value: str | None) -> Q:
        return Q()


@router.get("/snapshots", response=list[SnapshotSchema], url_name="get_snapshots")
@paginate(CustomPagination)
def get_snapshots(request: HttpRequest, filters: Query[SnapshotFilterSchema], with_archiveresults: bool = False):
    """List all Snapshot entries matching these filters."""
    setattr(request, "with_archiveresults", with_archiveresults)
    try:
        queryset = filter_snapshots_by_status(Snapshot.objects.all(), filters.status)
    except ValueError as err:
        raise HttpError(400, str(err)) from err
    queryset = filters.filter(queryset).distinct()
    query = (filters.search or "").strip()
    if not query:
        return queryset

    runtime_config = request.archivebox_config
    search_mode = get_search_mode(filters.search_mode, config=runtime_config)
    try:
        return apply_snapshot_search(
            queryset,
            query,
            search_mode=search_mode,
            config=runtime_config,
            include_id_matches=True,
        )
    except Exception:
        if get_search_mode_backend(search_mode, config=runtime_config):
            return queryset.none()
        return apply_snapshot_search(queryset, query, search_mode="meta", config=runtime_config, include_id_matches=True)


@router.get("/snapshots.rss", url_name="get_snapshots_rss")
def get_snapshots_rss(
    request: HttpRequest,
    crawl_id: str = "",
    created_by: str = "",
    limit: int = 50,
    before: str | None = None,
):
    """Return matching snapshots as an RSS feed, newest first."""
    snapshots = _filter_snapshots_for_rss(
        crawl_id=crawl_id,
        created_by=created_by,
        limit=limit,
        before=before,
    )
    return _snapshots_rss_response(request, snapshots=snapshots)


@router.get("/snapshot/{snapshot_id}", response=SnapshotSchema, url_name="get_snapshot")
def get_snapshot(request: HttpRequest, snapshot_id: str, with_archiveresults: bool = True):
    """Get a specific Snapshot by id."""
    setattr(request, "with_archiveresults", with_archiveresults)
    return _get_snapshot_by_ref(snapshot_id)


@router.post("/snapshots", response=SnapshotSchema, url_name="create_snapshot")
def create_snapshot(request: HttpRequest, data: SnapshotCreateSchema):
    tags = normalize_tag_list(data.tags)
    try:
        status = normalize_snapshot_status(data.status)
    except ValueError as err:
        raise HttpError(400, str(err)) from err
    if not data.url.strip():
        raise HttpError(400, "URL is required")
    try:
        validate_url_length(data.url.strip())
    except ValueError as err:
        raise HttpError(400, str(err)) from err
    if data.depth not in (0, 1, 2, 3, 4):
        raise HttpError(400, "depth must be between 0 and 4")

    if data.crawl_id:
        crawl = get_crawl_by_ref(data.crawl_id)
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

    # Browser uploads must not wait behind the runner's crawl-wide lifecycle
    # lock. The unique insert recovery and CAS update below are the request-side
    # coordination boundary for this idempotent metadata sync.
    snapshot = Snapshot.objects.filter(url=data.url, crawl=crawl).first()
    if snapshot is None:
        try:
            snapshot = Snapshot.objects.create(
                url=data.url,
                crawl=crawl,
                depth=data.depth,
                title=data.title,
                timestamp=str(timezone.now().timestamp()),
                status=status or Snapshot.StatusChoices.QUEUED,
                retry_at=timezone.now(),
            )
        except IntegrityError:
            snapshot = Snapshot.objects.filter(url=data.url, crawl=crawl).first()
            if snapshot is None:
                raise

    for _attempt in range(3):
        updates: dict[str, Any] = {}
        if data.title is not None and snapshot.title != data.title:
            updates["title"] = data.title
        if status is not None and snapshot.status != status:
            updates["status"] = status
        if not updates or snapshot.safe_update(updates, extra_filter={"modified_at": snapshot.modified_at}):
            break
    else:
        raise HttpError(409, "Snapshot changed while metadata was being updated")

    if tags:
        snapshot.save_tags(
            tags,
            created_by=request.user if isinstance(request.user, User) else None,
        )

    try:
        snapshot.ensure_crawl_symlink()
    except Exception:
        pass

    setattr(request, "with_archiveresults", False)
    return snapshot


@router.patch("/snapshot/{snapshot_id}", response=SnapshotSchema, url_name="patch_snapshot")
def patch_snapshot(request: HttpRequest, snapshot_id: str, data: SnapshotUpdateSchema):
    """Update a snapshot (e.g., set status=sealed to cancel queued work)."""
    snapshot = _get_snapshot_by_ref(snapshot_id)
    crawl_id = str(snapshot.crawl_id)

    payload = data.dict(exclude_unset=True)
    update_fields = ["modified_at"]
    action = payload.pop("action", None)
    tags = payload.pop("tags", None)

    if action:
        if action == "pause":
            snapshot.pause()
            setattr(request, "with_archiveresults", False)
            return snapshot
        if action in ("resume", "unpause"):
            snapshot.resume()
            setattr(request, "with_archiveresults", False)
            return snapshot
        if action == "cancel":
            snapshot.cancel()
            setattr(request, "with_archiveresults", False)
            return snapshot
        raise HttpError(400, f"Invalid action: {action}")

    with crawl_lifecycle_lock(crawl_id):
        snapshot = _get_snapshot_by_ref(snapshot_id)
        if "status" in payload:
            try:
                snapshot.status = normalize_snapshot_status(payload["status"])
            except ValueError as err:
                raise HttpError(400, str(err)) from err
            if snapshot.status == Snapshot.StatusChoices.SEALED and "retry_at" not in payload:
                snapshot.retry_at = None
            update_fields.append("status")

        if "retry_at" in payload:
            snapshot.retry_at = payload["retry_at"]
            update_fields.append("retry_at")

        if tags is not None:
            snapshot.save_tags(
                normalize_tag_list(tags),
                created_by=request.user if isinstance(request.user, User) else None,
            )

        if payload.get("status") == Snapshot.StatusChoices.SEALED:
            snapshot.cancel()
        else:
            snapshot.save(update_fields=update_fields)
    setattr(request, "with_archiveresults", False)
    return snapshot


@router.delete("/snapshot/{snapshot_id}", response=SnapshotDeleteResponseSchema, url_name="delete_snapshot")
def delete_snapshot(request: HttpRequest, snapshot_id: str):
    snapshot = get_snapshot(request, snapshot_id, with_archiveresults=False)
    snapshot_id_str = str(snapshot.id)
    crawl_id_str = str(snapshot.crawl.pk)
    snapshot.cancel()

    from archivebox.services.runner import run_pending_crawls

    with crawl_lifecycle_lock(crawl_id_str):
        run_pending_crawls(crawl_id=crawl_id_str, daemon=False)
        snapshot = get_snapshot(request, snapshot_id_str, with_archiveresults=False)
        deleted_count, _ = snapshot.delete()
    return {
        "success": True,
        "snapshot_id": snapshot_id_str,
        "crawl_id": crawl_id_str,
        "deleted_count": deleted_count,
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
        username = user.username
        return username if isinstance(username, str) else str(user)

    @staticmethod
    def resolve_num_snapshots(obj, context):
        return obj.snapshot_set.all().distinct().count()

    @staticmethod
    def resolve_snapshots(obj, context):
        if bool(context["request"].__dict__.get("with_snapshots", False)):
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
    snapshot = _get_snapshot_for_tag_edit(data.snapshot_id)

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
