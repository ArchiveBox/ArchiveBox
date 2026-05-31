__package__ = "archivebox.api"

from pathlib import Path
from uuid import UUID
from datetime import datetime
from django.http import FileResponse, HttpRequest
from django.shortcuts import redirect
from django.utils import timezone

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User

from ninja import Router, Schema
from ninja.errors import HttpError

from archivebox.core.models import Snapshot
from archivebox.core.permissions import (
    PERMISSIONS_PUBLIC,
    PERMISSIONS_UNLISTED,
    is_admin_user,
    normalize_permissions,
)
from archivebox.config.common import get_config
from archivebox.crawls.models import Crawl
from archivebox.misc.util import filter_queryset_by_uuid_substring

from .auth import API_AUTH_METHODS, auth_using_token

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
    is_paused: bool

    urls: str
    max_depth: int
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
    def resolve_config(obj):
        # Redact credential values so REST responses can never leak the raw
        # token/secret/api-key that the operator stored in Crawl.config.
        from archivebox.config.common import redact_sensitive_config

        return redact_sensitive_config(obj.config)

    @staticmethod
    def resolve_snapshots(obj, context):
        if bool(getattr(context["request"], "with_snapshots", False)):
            return obj.snapshot_set.all().distinct()
        return Snapshot.objects.none()


class CrawlUpdateSchema(Schema):
    action: str | None = None
    status: str | None = None
    retry_at: datetime | None = None
    tags: list[str] | None = None
    tags_str: str | None = None


class CrawlCreateSchema(Schema):
    urls: list[str]
    max_depth: int = 0
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

    tags = normalize_tag_list(data.tags, data.tags_str)
    config = dict(data.config or {})
    request_user = request.user if request.user.is_authenticated else None
    config.setdefault("PERMISSIONS", str(get_config(user=request_user).PERMISSIONS))
    crawl = Crawl.objects.create(
        urls="\n".join(urls),
        max_depth=data.max_depth,
        tags_str=",".join(tags),
        label=data.label,
        notes=data.notes,
        config=config,
        status=Crawl.StatusChoices.QUEUED,
        retry_at=timezone.now(),
        created_by=request.user if isinstance(request.user, User) else None,
    )
    return crawl


@router.get("/crawl/{crawl_id}", response=CrawlSchema, url_name="get_crawl")
def get_crawl(request: HttpRequest, crawl_id: str, as_rss: bool = False, with_snapshots: bool = False, with_archiveresults: bool = False):
    """Get a specific Crawl by id."""
    setattr(request, "with_snapshots", with_snapshots)
    setattr(request, "with_archiveresults", with_archiveresults)
    crawl = filter_queryset_by_uuid_substring(Crawl.objects.all(), crawl_id).get()

    if crawl and as_rss:
        query = request.GET.copy()
        query.pop("as_rss", None)
        query["crawl_id"] = str(crawl.id)
        return redirect(f"/api/v1/core/snapshots.rss?{query.urlencode()}")

    return crawl


def crawl_file(request: HttpRequest, crawl_id: str, path: str):
    # Try to resolve the crawl first; if it doesn't exist, return 404.
    try:
        crawl = filter_queryset_by_uuid_substring(Crawl.objects.all(), crawl_id).get()
    except Crawl.DoesNotExist:
        raise HttpError(404, "Crawl not found")

    # Determine the effective viewer: session user takes precedence, otherwise
    # fall back to an API token passed via ?api_key=, X-ArchiveBox-API-Key, or
    # Authorization: Bearer ... (so that programmatic clients still work).
    user = getattr(request, "user", None)
    is_authenticated = bool(getattr(user, "is_authenticated", False) and getattr(user, "is_active", False))
    if not is_authenticated:
        token = request.GET.get("api_key") or request.headers.get("X-ArchiveBox-API-Key")
        auth_header = request.headers.get("Authorization", "")
        if not token and auth_header.lower().startswith("bearer "):
            token = auth_header.split(None, 1)[1].strip()
        token_user = auth_using_token(token=token, request=request) if token else None
        if token_user and token_user.is_active:
            user = token_user
            is_authenticated = True
            # Re-bind so is_admin_user() / ownership checks below see the token user.
            setattr(request, "user", token_user)

    # Gate access using the same model as SnapshotView/can_view_snapshot:
    # admins always pass; owners can see their own crawls; otherwise the crawl
    # must be PUBLIC or UNLISTED. Don't disclose existence of private crawls.
    if not is_admin_user(request):
        permissions = normalize_permissions(crawl.permissions)
        is_owner = bool(is_authenticated and getattr(crawl, "created_by_id", None) == getattr(user, "id", None))
        if not is_owner and permissions not in {PERMISSIONS_PUBLIC, PERMISSIONS_UNLISTED}:
            raise HttpError(404, "Crawl not found")

    crawl_root = Path(crawl.output_dir).resolve()
    file_path = (crawl_root / path).resolve()
    if not file_path.is_file() or crawl_root not in file_path.parents:
        raise HttpError(404, "Crawl file not found")

    response = FileResponse(file_path.open("rb"))
    response["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/crawl/{crawl_id}/files/{filename}", auth=None, url_name="crawl_file_root")
def crawl_file_root(request: HttpRequest, crawl_id: str, filename: str):
    return crawl_file(request, crawl_id, filename)


@router.get("/crawl/{crawl_id}/files/{folder}/{filename}", auth=None, url_name="crawl_file_nested_1")
def crawl_file_nested_1(request: HttpRequest, crawl_id: str, folder: str, filename: str):
    return crawl_file(request, crawl_id, f"{folder}/{filename}")


@router.get("/crawl/{crawl_id}/files/{folder}/{subfolder}/{filename}", auth=None, url_name="crawl_file_nested_2")
def crawl_file_nested_2(request: HttpRequest, crawl_id: str, folder: str, subfolder: str, filename: str):
    return crawl_file(request, crawl_id, f"{folder}/{subfolder}/{filename}")


@router.patch("/crawl/{crawl_id}", response=CrawlSchema, url_name="patch_crawl")
def patch_crawl(request: HttpRequest, crawl_id: str, data: CrawlUpdateSchema):
    """Update a crawl (e.g., set status=sealed to cancel queued work)."""
    crawl = filter_queryset_by_uuid_substring(Crawl.objects.all(), crawl_id).get()
    payload = data.dict(exclude_unset=True)
    update_fields = ["modified_at"]

    action = payload.pop("action", None)
    if action:
        if action == "pause":
            crawl.pause()
            return crawl
        if action in ("resume", "unpause"):
            crawl.resume()
            return crawl
        if action == "cancel":
            crawl.cancel()
            return crawl
        raise HttpError(400, f"Invalid action: {action}")

    tags = payload.pop("tags", None)
    tags_str = payload.pop("tags_str", None)
    if tags is not None or tags_str is not None:
        crawl.tags_str = ",".join(normalize_tag_list(tags, tags_str or ""))
        update_fields.append("tags_str")

    if "status" in payload:
        if payload["status"] not in Crawl.StatusChoices.values:
            raise HttpError(400, f"Invalid status: {payload['status']}")
        if payload["status"] == Crawl.StatusChoices.SEALED:
            crawl.cancel()
            return crawl
        crawl.status = payload["status"]
        update_fields.append("status")

    if "retry_at" in payload:
        crawl.retry_at = payload["retry_at"]
        update_fields.append("retry_at")

    crawl.save(update_fields=update_fields)
    return crawl


@router.delete("/crawl/{crawl_id}", response=CrawlDeleteResponseSchema, url_name="delete_crawl")
def delete_crawl(request: HttpRequest, crawl_id: str):
    crawl = filter_queryset_by_uuid_substring(Crawl.objects.all(), crawl_id).get()
    crawl_id_str = str(crawl.id)
    snapshot_count = crawl.snapshot_set.count()
    deleted_count, _ = crawl.delete()
    return {
        "success": True,
        "crawl_id": crawl_id_str,
        "deleted_count": deleted_count,
        "deleted_snapshots": snapshot_count,
    }
