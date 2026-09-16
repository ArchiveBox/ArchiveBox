import json
import mimetypes
import re
from pathlib import Path, PurePosixPath
from typing import Any

from django.core.files.storage import FileSystemStorage
from django.http import HttpRequest
from django.http.multipartparser import MultiPartParser, MultiPartParserError
from django.utils import timezone
from ninja import Form, Query, Router, UploadedFile
from ninja.errors import HttpError
from ninja.pagination import paginate

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.misc.db import uuid_ref_query as _uuid_ref_query

from .lookup import _get_snapshot_by_ref
from .pagination import CustomPagination
from .schemas import ArchiveResultFilterSchema, ArchiveResultSchema

router = Router(tags=["Core Models"])

ARCHIVERESULT_UPLOAD_HOOK_NAME = Snapshot.BROWSER_EXTENSION_UPLOAD_HOOK_NAME
ARCHIVERESULT_UPLOAD_PLUGIN_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


@router.get("/archiveresults", response=list[ArchiveResultSchema], url_name="get_archiveresult")
@paginate(CustomPagination)
def get_archiveresults(request: HttpRequest, filters: Query[ArchiveResultFilterSchema]):
    """List all ArchiveResult entries matching these filters."""
    queryset = filters.filter(ArchiveResult.objects.all())
    if filters.search or filters.snapshot_tag:
        return queryset.distinct()
    return queryset


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
