from __future__ import annotations

import json
from collections import defaultdict
from typing import Any
from urllib.parse import unquote

from django.contrib.auth.models import User
from django.db.models import Count, F, QuerySet
from django.db.models.functions import Lower
from django.http import HttpRequest
from django.urls import reverse

from archivebox.core.host_utils import build_snapshot_url, build_web_url
from archivebox.core.models import Snapshot, SnapshotTag, Tag


TAG_SNAPSHOT_PREVIEW_LIMIT = 10
TAG_SORT_CHOICES = (
    ("name_asc", "Name A-Z"),
    ("name_desc", "Name Z-A"),
    ("created_desc", "Created newest"),
    ("created_asc", "Created oldest"),
    ("snapshots_desc", "Most snapshots"),
    ("snapshots_asc", "Fewest snapshots"),
)
TAG_HAS_SNAPSHOTS_CHOICES = (
    ("all", "All"),
    ("yes", "Has snapshots"),
    ("no", "No snapshots"),
)


def normalize_tag_name(name: str) -> str:
    return (name or "").strip()


def normalize_tag_sort(sort: str = "created_desc") -> str:
    valid_sorts = {key for key, _label in TAG_SORT_CHOICES}
    return sort if sort in valid_sorts else "created_desc"


def normalize_has_snapshots_filter(value: str = "all") -> str:
    valid_filters = {key for key, _label in TAG_HAS_SNAPSHOTS_CHOICES}
    return value if value in valid_filters else "all"


def normalize_created_by_filter(created_by: str = "") -> str:
    return created_by if str(created_by).isdigit() else ""


def normalize_created_year_filter(year: str = "") -> str:
    year = (year or "").strip()
    return year if len(year) == 4 and year.isdigit() else ""


def get_matching_tags(
    query: str = "",
    sort: str = "created_desc",
    created_by: str = "",
    year: str = "",
    has_snapshots: str = "all",
) -> QuerySet[Tag]:
    queryset = Tag.objects.select_related("created_by").annotate(
        num_snapshots=Count("snapshot_set", distinct=True),
    )

    query = normalize_tag_name(query)
    if query:
        queryset = queryset.filter(name__icontains=query)

    created_by = normalize_created_by_filter(created_by)
    if created_by:
        queryset = queryset.filter(created_by_id=int(created_by))

    year = normalize_created_year_filter(year)
    if year:
        queryset = queryset.filter(created_at__year=int(year))

    has_snapshots = normalize_has_snapshots_filter(has_snapshots)
    if has_snapshots == "yes":
        queryset = queryset.filter(num_snapshots__gt=0)
    elif has_snapshots == "no":
        queryset = queryset.filter(num_snapshots=0)

    sort = normalize_tag_sort(sort)
    if sort == "name_asc":
        queryset = queryset.order_by(Lower("name"), "id")
    elif sort == "name_desc":
        queryset = queryset.order_by(Lower("name").desc(), "-id")
    elif sort == "created_asc":
        queryset = queryset.order_by(F("created_at").asc(nulls_first=True), "id", Lower("name"))
    elif sort == "snapshots_desc":
        queryset = queryset.order_by(F("num_snapshots").desc(nulls_last=True), F("created_at").desc(nulls_last=True), "-id", Lower("name"))
    elif sort == "snapshots_asc":
        queryset = queryset.order_by(F("num_snapshots").asc(nulls_first=True), Lower("name"), "id")
    else:
        queryset = queryset.order_by(F("created_at").desc(nulls_last=True), "-id", Lower("name"))

    return queryset


def get_tag_creator_choices() -> list[tuple[str, str]]:
    rows = (
        Tag.objects.filter(created_by__isnull=False)
        .values_list("created_by_id", "created_by__username")
        .order_by(Lower("created_by__username"), "created_by_id")
        .distinct()
    )
    return [(str(user_id), username or f"User {user_id}") for user_id, username in rows]


def get_tag_year_choices() -> list[str]:
    years = Tag.objects.exclude(created_at__isnull=True).dates("created_at", "year", order="DESC")
    return [str(year.year) for year in years]


def get_tag_by_ref(tag_ref: str | int) -> Tag:
    if isinstance(tag_ref, int):
        return Tag.objects.get(pk=tag_ref)

    ref = str(tag_ref).strip()
    if ref.isdigit():
        return Tag.objects.get(pk=int(ref))

    decoded = unquote(ref)
    return Tag.objects.get(name__iexact=decoded)


def get_or_create_tag(name: str, created_by: User | None = None) -> tuple[Tag, bool]:
    normalized_name = normalize_tag_name(name)
    if not normalized_name:
        raise ValueError("Tag name is required")

    existing = Tag.objects.filter(name__iexact=normalized_name).first()
    if existing:
        return existing, False

    tag = Tag.objects.create(
        name=normalized_name,
        created_by=created_by,
    )
    return tag, True


def rename_tag(tag: Tag, name: str) -> Tag:
    normalized_name = normalize_tag_name(name)
    if not normalized_name:
        raise ValueError("Tag name is required")

    existing = Tag.objects.filter(name__iexact=normalized_name).exclude(pk=tag.pk).first()
    if existing:
        raise ValueError(f'Tag "{existing.name}" already exists')

    if tag.name != normalized_name:
        tag.name = normalized_name
        tag.save()
    return tag


def delete_tag(tag: Tag) -> tuple[int, dict[str, int]]:
    return tag.delete()


def export_tag_urls(tag: Tag) -> str:
    urls = tag.snapshot_set.order_by("-downloaded_at", "-created_at", "-pk").values_list("url", flat=True)
    return "\n".join(urls)


def export_tag_snapshots_jsonl(tag: Tag) -> str:
    snapshots = tag.snapshot_set.order_by("-downloaded_at", "-created_at", "-pk").prefetch_related("tags")
    return "\n".join(json.dumps(snapshot.to_json()) for snapshot in snapshots)


def _display_snapshot_title(snapshot: Snapshot) -> str:
    title = (snapshot.title or "").strip()
    url = (snapshot.url or "").strip()
    if not title:
        return url

    normalized_title = title.lower()
    if normalized_title == "pending..." or normalized_title == url.lower():
        return url
    return title


def _build_snapshot_preview(snapshot: Snapshot, request: HttpRequest | None = None) -> dict[str, Any]:
    return {
        "id": str(snapshot.pk),
        "title": _display_snapshot_title(snapshot),
        "url": snapshot.url,
        "favicon_url": build_snapshot_url(str(snapshot.pk), "favicon.ico", request=request),
        "admin_url": reverse("admin:core_snapshot_change", args=[snapshot.pk]),
        "archive_url": build_web_url(f"/{snapshot.archive_path_from_db}/index.html", request=request),
        "downloaded_at": snapshot.downloaded_at.isoformat() if snapshot.downloaded_at else None,
    }


def _build_snapshot_preview_map(
    tags: list[Tag],
    request: HttpRequest | None = None,
    preview_limit: int = TAG_SNAPSHOT_PREVIEW_LIMIT,
) -> dict[int, list[dict[str, Any]]]:
    tag_ids = [tag.pk for tag in tags]
    if not tag_ids:
        return {}

    snapshot_tags = (
        SnapshotTag.objects.filter(tag_id__in=tag_ids)
        .select_related("snapshot__crawl__created_by")
        .order_by(
            "tag_id",
            F("snapshot__downloaded_at").desc(nulls_last=True),
            F("snapshot__created_at").desc(nulls_last=True),
            F("snapshot_id").desc(),
        )
    )

    preview_map: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for snapshot_tag in snapshot_tags:
        previews = preview_map[snapshot_tag.tag_id]
        if len(previews) >= preview_limit:
            continue
        previews.append(_build_snapshot_preview(snapshot_tag.snapshot, request=request))
    return preview_map


def build_tag_card(tag: Tag, snapshot_previews: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    count = getattr(tag, "num_snapshots", tag.snapshot_set.count())
    return {
        "id": tag.pk,
        "name": tag.name,
        "num_snapshots": count,
        "filter_url": f"{reverse('admin:core_snapshot_changelist')}?tags__id__exact={tag.pk}",
        "edit_url": reverse("admin:core_tag_change", args=[tag.pk]),
        "export_urls_url": reverse("api-1:tag_urls_export", args=[tag.pk]),
        "export_jsonl_url": reverse("api-1:tag_snapshots_export", args=[tag.pk]),
        "rename_url": reverse("api-1:rename_tag", args=[tag.pk]),
        "delete_url": reverse("api-1:delete_tag", args=[tag.pk]),
        "snapshots": snapshot_previews or [],
    }


def build_tag_cards(
    query: str = "",
    request: HttpRequest | None = None,
    limit: int | None = None,
    preview_limit: int = TAG_SNAPSHOT_PREVIEW_LIMIT,
    sort: str = "created_desc",
    created_by: str = "",
    year: str = "",
    has_snapshots: str = "all",
) -> list[dict[str, Any]]:
    queryset = get_matching_tags(
        query=query,
        sort=sort,
        created_by=created_by,
        year=year,
        has_snapshots=has_snapshots,
    )
    if limit is not None:
        queryset = queryset[:limit]

    tags = list(queryset)
    preview_map = _build_snapshot_preview_map(tags, request=request, preview_limit=preview_limit)
    return [build_tag_card(tag, snapshot_previews=preview_map.get(tag.pk, [])) for tag in tags]
