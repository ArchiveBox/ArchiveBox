from collections import defaultdict
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from django.db.models import Q
from archivebox.api.schemas import OwnedObjectSchema

from ninja import FilterLookup, FilterSchema, Schema

from archivebox.core.models import ArchiveResult, Snapshot


class MinimalArchiveResultSchema(OwnedObjectSchema):
    TYPE: str = "core.models.ArchiveResult"
    id: UUID
    created_at: datetime | None
    modified_at: datetime | None
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


class SnapshotSchema(OwnedObjectSchema):
    TYPE: str = "core.models.Snapshot"
    id: UUID
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


class TagSchema(OwnedObjectSchema):
    TYPE: str = "core.models.Tag"
    id: int
    modified_at: datetime
    created_at: datetime
    name: str
    num_snapshots: int
    snapshots: list[SnapshotSchema]

    @staticmethod
    def resolve_num_snapshots(obj, context):
        return obj.snapshot_set.all().distinct().count()

    @staticmethod
    def resolve_snapshots(obj, context):
        if bool(context["request"].__dict__.get("with_snapshots", False)):
            return obj.snapshot_set.all().distinct()
        return Snapshot.objects.none()


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
