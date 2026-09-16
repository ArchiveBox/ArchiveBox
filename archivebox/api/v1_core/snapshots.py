from datetime import datetime, time
from html import unescape
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.feedgenerator import Rss201rev2Feed
from ninja import Query, Router
from ninja.errors import HttpError
from ninja.pagination import paginate

from archivebox.api.v1_crawls import get_crawl_by_ref
from archivebox.core.models import Snapshot
from archivebox.core.routes_util import build_web_url
from archivebox.core.snapshot_status import filter_snapshots_by_status, normalize_snapshot_status
from archivebox.crawls.locks import crawl_lifecycle_lock
from archivebox.crawls.models import Crawl
from archivebox.misc.util import filter_queryset_by_uuid_substring, validate_url_length
from archivebox.search.config import get_search_mode, get_search_mode_backend
from archivebox.search.query import apply_snapshot_search

from .lookup import _get_snapshot_by_ref
from .pagination import CustomPagination
from .schemas import SnapshotCreateSchema, SnapshotDeleteResponseSchema, SnapshotFilterSchema, SnapshotSchema, SnapshotUpdateSchema

router = Router(tags=["Core Models"])


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
