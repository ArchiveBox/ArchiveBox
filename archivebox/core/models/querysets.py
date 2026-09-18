from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from django.core.exceptions import FieldDoesNotExist
from django.db import models

from archivebox.config import CONSTANTS
from archivebox.config.common import get_config
from archivebox.crawls.models import Crawl
from archivebox.misc.system import atomic_write
from archivebox.misc.util import (
    to_json,
)


class UngroupedSubquery(models.Subquery):
    """Scalar subquery that should not be copied into the outer GROUP BY."""

    def get_group_by_cols(self):
        return []


class SnapshotQuerySet(models.QuerySet):
    """Custom QuerySet for Snapshot model with export methods that persist through .filter() etc."""

    def bulk_create(self, objs, *args, **kwargs):
        objs = list(objs)
        missing_crawl_ids = set()
        from archivebox.core.permissions import PERMISSIONS_VALUES

        for obj in objs:
            if isinstance(obj, self.model):
                config = dict(obj.config or {})
                permission = str(config.get("PERMISSIONS") or "").strip().lower()
                if permission not in PERMISSIONS_VALUES and obj.crawl_id:
                    crawl = getattr(obj, "crawl", None)
                    if not getattr(crawl, "permissions", None):
                        missing_crawl_ids.add(str(obj.crawl_id))

        crawl_permissions_by_id = {}
        if missing_crawl_ids:
            crawl_permissions_by_id = {
                str(crawl_id): permissions
                for crawl_id, permissions in Crawl.objects.filter(pk__in=missing_crawl_ids).values_list("pk", "permissions")
            }

        from archivebox.misc.db import truncate_overlong_charfields

        for obj in objs:
            if isinstance(obj, self.model):
                obj.ensure_permissions_config(crawl_permissions=crawl_permissions_by_id.get(str(obj.crawl_id)))
                # bulk_create bypasses pre_save, so clamp CharFields here too
                # (e.g. page titles) to stay within postgres VARCHAR limits.
                truncate_overlong_charfields(obj)
        return super().bulk_create(objs, *args, **kwargs)

    def paged_iterator(self, chunk_size: int = 500):
        """
        Iterate snapshots using bounded keyset pages instead of one streaming cursor.

        Django's iterator(chunk_size=...) still keeps a single SQLite SELECT
        cursor open until the full queryset is exhausted. That is fine for
        read-only exports, but update/migration code does filesystem work and
        writes while iterating; a long-lived read cursor there can stretch lock
        waits across thousands of rows. This respects the queryset's existing
        filters, order_by(), select_related(), and prefetch_related() state; if
        no ordering is defined, it falls back to primary-key order.
        """
        pk_field = self.model._meta.pk.name
        raw_ordering = tuple(self.query.order_by or self.model._meta.ordering or (pk_field,))

        ordering = []
        for term in raw_ordering:
            if not isinstance(term, str) or term == "?":
                ordering = []
                break
            field_name = term.removeprefix("-")
            field_name = pk_field if field_name == "pk" else field_name
            ordering.append(f"-{field_name}" if term.startswith("-") else field_name)

        ordered_field_names = [term.removeprefix("-") for term in ordering]
        unique_field_names = {pk_field, *(field.name for field in self.model._meta.fields if field.unique)}
        try:
            use_keyset = any(name in unique_field_names for name in ordered_field_names) and not any(
                self.model._meta.get_field(name).null for name in ordered_field_names
            )
        except (AttributeError, FieldDoesNotExist):
            use_keyset = False
        # Expressions, nullable/related fields and non-unique orderings retain
        # Django's ordering through bounded offset pages.
        if not use_keyset:
            offset = 0
            while batch := list(self[offset : offset + chunk_size]):
                yield from batch
                offset += chunk_size
            return

        last_values = None
        value_field_names = tuple(dict.fromkeys([*ordered_field_names, pk_field]))
        while True:
            batch_qs = self.order_by(*ordering)
            if last_values is not None:
                page_filter = models.Q()
                for idx, term in enumerate(ordering):
                    descending = term.startswith("-")
                    field_name = term[1:] if descending else term
                    prefix = {ordered_field_names[i]: last_values[i] for i in range(idx)}
                    comparison = "lt" if descending else "gt"
                    page_filter |= models.Q(**prefix, **{f"{field_name}__{comparison}": last_values[idx]})
                batch_qs = batch_qs.filter(page_filter)

            batch_rows = list(batch_qs.values_list(*value_field_names)[:chunk_size])
            if not batch_rows:
                break

            pk_idx = value_field_names.index(pk_field)
            snapshot_ids = [row[pk_idx] for row in batch_rows]
            snapshots_by_id = {snapshot.pk: snapshot for snapshot in self.filter(pk__in=snapshot_ids).order_by()}

            for row in batch_rows:
                snapshot_id = row[pk_idx]
                snapshot = snapshots_by_id.get(snapshot_id)
                if snapshot is not None:
                    yield snapshot

            last_values = batch_rows[-1][: len(ordered_field_names)]

    # =========================================================================
    # Filtering Methods
    # =========================================================================

    FILTER_TYPES: ClassVar[dict[str, Any]] = {
        "exact": lambda pattern: models.Q(url=pattern),
        "substring": lambda pattern: models.Q(url__icontains=pattern),
        "regex": lambda pattern: models.Q(url__iregex=pattern),
        "domain": lambda pattern: (
            models.Q(url__istartswith=f"http://{pattern}")
            | models.Q(url__istartswith=f"https://{pattern}")
            | models.Q(url__istartswith=f"ftp://{pattern}")
        ),
        "tag": lambda pattern: models.Q(tags__name=pattern),
        "timestamp": lambda pattern: models.Q(timestamp=pattern),
    }
    FILTER_TYPE_CHOICES = tuple(FILTER_TYPES)
    FILTER_ARG_KEYS = (
        "after",
        "before",
        "filter_type",
        "filter_patterns",
        "status",
        "url__icontains",
        "url__istartswith",
        "tag",
        "crawl_id",
        "limit",
        "sort",
        "search",
    )
    SPECIAL_FILTER_ARG_KEYS = frozenset({"filter_patterns", "filter_type", "query", "search", "tag", "before", "after", "limit", "sort"})

    def filter_by_patterns(self, patterns: list[str], filter_type: str = "exact") -> SnapshotQuerySet:
        """Filter snapshots by URL patterns using specified filter type"""
        from archivebox.misc.logging import stderr

        q_filter = models.Q()
        for pattern in patterns:
            try:
                q_filter = q_filter | self.FILTER_TYPES[filter_type](pattern)
            except KeyError:
                stderr()
                stderr(f"[X] Got invalid pattern for --filter-type={filter_type}:", color="red")
                stderr(f"    {pattern}")
                raise SystemExit(2)
        return self.filter(q_filter)

    def search(self, **kwargs) -> SnapshotQuerySet:

        from archivebox.core.snapshot_status import filter_snapshots_by_status
        from archivebox.search.query import apply_snapshot_search

        queryset = self
        filter_patterns = tuple(str(pattern) for pattern in kwargs.get("filter_patterns") or ())
        filter_type = kwargs.get("filter_type") or "substring"
        query = kwargs.get("query")
        if isinstance(query, (list, tuple)):
            query = " ".join(str(part) for part in query)
        query = (query or (" ".join(filter_patterns) if kwargs.get("search") else "")).strip()

        field_names = {field.name for field in self.model._meta.get_fields()}
        field_names.update(field.attname for field in self.model._meta.fields)
        field_filters = {
            key: value
            for key, value in kwargs.items()
            if value is not None and key not in self.SPECIAL_FILTER_ARG_KEYS and key.split("__", 1)[0] in field_names
        }
        status = field_filters.pop("status", None)
        queryset = filter_snapshots_by_status(queryset, status)
        if field_filters:
            queryset = queryset.filter(**field_filters)
        if kwargs.get("tag"):
            queryset = queryset.filter(tags__name__iexact=kwargs["tag"])
        if kwargs.get("before") is not None:
            queryset = queryset.filter(bookmarked_at__lt=datetime.fromtimestamp(float(kwargs["before"]), tz=UTC))
        if kwargs.get("after") is not None:
            queryset = queryset.filter(bookmarked_at__gt=datetime.fromtimestamp(float(kwargs["after"]), tz=UTC))

        if query:
            queryset = apply_snapshot_search(
                queryset,
                query,
                search_mode=kwargs.get("search"),
                ordering=("-created_at",) if not kwargs.get("sort") else None,
                max_results=kwargs.get("limit"),
                skip_backend_when_metadata_satisfies_limit=True,
                include_metadata_for_forced_backend=True,
            )
        elif filter_patterns:
            queryset = queryset.filter_by_patterns(list(filter_patterns), filter_type)

        if kwargs.get("sort"):
            queryset = queryset.order_by(kwargs["sort"])
        elif not queryset.query.order_by:
            queryset = queryset.order_by("-created_at")

        limit = kwargs.get("limit")
        if limit is not None and limit > 0:
            queryset = queryset[:limit]

        return queryset

    # =========================================================================
    # Export Methods
    # =========================================================================

    def to_json(self, with_headers: bool = False) -> str:
        """Generate JSON index from snapshots"""
        import sys
        from datetime import datetime

        from archivebox.config import VERSION

        config = get_config()

        MAIN_INDEX_HEADER = (
            {
                "info": "This is an index of site data archived by ArchiveBox: The self-hosted web archive.",
                "schema": "archivebox.index.json",
                "copyright_info": config.FOOTER_INFO,
                "meta": {
                    "project": "ArchiveBox",
                    "version": VERSION,
                    "git_sha": VERSION,
                    "website": "https://ArchiveBox.io",
                    "docs": "https://github.com/ArchiveBox/ArchiveBox/wiki",
                    "source": "https://github.com/ArchiveBox/ArchiveBox",
                    "issues": "https://github.com/ArchiveBox/ArchiveBox/issues",
                    "dependencies": {},
                },
            }
            if with_headers
            else {}
        )

        snapshot_dicts = [s.to_dict(extended=True, static_export=True) for s in self.iterator(chunk_size=500)]

        if with_headers:
            output = {
                **MAIN_INDEX_HEADER,
                "num_links": len(snapshot_dicts),
                "updated": datetime.now(UTC),
                "last_run_cmd": sys.argv,
                "links": snapshot_dicts,
            }
        else:
            output = snapshot_dicts
        return to_json(output, indent=4, sort_keys=True)

    def to_csv(self, cols: list[str] | None = None, header: bool = True, separator: str = ",", ljust: int = 0) -> str:
        """Generate CSV output from snapshots"""
        cols = cols or ["timestamp", "is_archived", "url"]
        header_str = separator.join(col.ljust(ljust) for col in cols) if header else ""
        row_strs = (s.to_csv(cols=cols, ljust=ljust, separator=separator) for s in self.iterator(chunk_size=500))
        return "\n".join((header_str, *row_strs))

    def to_html(self, with_headers: bool = True) -> str:
        """Generate main index HTML from snapshots"""
        from datetime import datetime

        from django.template.loader import render_to_string

        from archivebox.config import VERSION
        from archivebox.config.version import get_COMMIT_HASH

        config = get_config()

        template = "static_index.html" if with_headers else "minimal_index.html"
        snapshot_list = list(self.iterator(chunk_size=500))
        manifest_records = []
        for snapshot in snapshot_list:
            outputs = snapshot.discover_outputs(include_filesystem_fallback=True)
            output_paths = [str(output.get("path") or "") for output in outputs]
            snapshot._public_preview_paths = [
                path for preferred in ("screenshot/screenshot.png", "screenshot.png") for path in output_paths if path == preferred
            ]
            snapshot._public_favicon_paths = [path for path in output_paths if path in ("favicon/favicon.ico", "favicon.ico")]
            snapshot.write_html_details()
            if with_headers:
                # Use the same portable schema as the JSON export. Rendering
                # above has already populated result-count caches, archive_size
                # reuses the sealed output_size field, and tags are prefetched.
                manifest_records.append(snapshot.to_dict(extended=True, static_export=True))

        if with_headers:
            manifest = "".join(f"{to_json(record, indent=None, sort_keys=True)}\n" for record in manifest_records)
            atomic_write(str(CONSTANTS.DATA_DIR / CONSTANTS.JSONL_INDEX_FILENAME), manifest)

        return render_to_string(
            template,
            {
                "version": VERSION,
                "git_sha": get_COMMIT_HASH() or VERSION,
                "num_links": str(len(snapshot_list)),
                "date_updated": datetime.now(UTC).strftime("%Y-%m-%d"),
                "time_updated": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
                "links": snapshot_list,
                "FOOTER_INFO": config.FOOTER_INFO,
                "STATIC_EXPORT": True,
                "STATIC_EXPORT_DIR": CONSTANTS.DATA_DIR,
            },
        )


class SnapshotManager(models.Manager.from_queryset(SnapshotQuerySet)):  # ty: ignore[unsupported-base]
    """Manager for Snapshot model - uses SnapshotQuerySet for chainable methods"""

    def filter(self, *args, **kwargs):
        domain = kwargs.pop("domain", None)
        qs = super().filter(*args, **kwargs)
        if domain:
            qs = qs.filter(url__icontains=f"://{domain}")
        return qs

    def get_queryset(self):
        # Don't prefetch by default - it causes "too many open files" during bulk operations
        # Views/templates can add .prefetch_related('tags', 'archiveresult_set') where needed
        return super().get_queryset()

    # =========================================================================
    # Import Methods
    # =========================================================================

    def remove(self, atomic: bool = False) -> tuple:
        """Remove snapshots from the database"""
        from django.db import transaction

        if atomic:
            with transaction.atomic():
                return self.get_queryset().delete()
        return self.get_queryset().delete()
