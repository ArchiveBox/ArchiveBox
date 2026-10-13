"""ArchiveResult summaries for snapshot list pages.

The public index and the admin snapshot changelist show, per snapshot:
progress counts, per-plugin sizes, one file icon per successful plugin
(linking to that result's embed path), a favicon and a thumbnail.

Loading every result as a model instance with its ``output_files`` manifest
used to dominate these pages: model construction (field converters, signals,
descriptors) for every row, plus decoding manifests nothing renders. Here:

- every result is one plain value row, never a model instance;
- sizes come from the materialized ``output_size`` column;
- the same query ships ``output_files`` (as text) only for rows that can
  render a link: successful results and thumbnail candidates. Queued, failed
  and skipped rows never transfer theirs, and a shipped manifest is decoded
  only when rendering asks that result for its link.

List pages must never read the archive filesystem; nothing here does.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.db import connection
from django.db.models import BooleanField, Case, CharField, Q, TextField, Value, When
from django.db.models.functions import Cast
from django.db.models.base import DEFERRED

from archivebox.core.models import ArchiveResult
from archivebox.uuid_compat import compact_uuid

if TYPE_CHECKING:
    from collections.abc import Iterable


_UNRESOLVED = object()

# A result's embed path only changes with its row. Decoding manifests (some list
# thousands of files) on every page view was the largest part of the snapshot
# list's time on prod, so resolve each once per row version, per process.
_EMBED_PATHS: dict[str, tuple[tuple[Any, ...], str | None]] = {}
_EMBED_PATHS_MAX = 50_000


@dataclass(slots=True, eq=False)
class ListResult:
    """One ArchiveResult as list pages read it: a value row, not a model instance.

    Duck-types the attributes and ``embed_path()`` that icon, favicon and
    thumbnail rendering read from ArchiveResult instances. Ids are hex
    strings, the way CompactUUIDs print.
    """

    id: str
    snapshot_id: str
    plugin: str
    status: str
    output_size: int
    output_str: str
    # Row version (modified_at, size, status) keying the process-wide path cache.
    version: tuple[Any, ...] = ()
    # Undecoded output_files JSON, fetched only for rows that can render a link
    # and whose path is not cached for this version.
    output_files_json: str | None = None
    _embed_path: Any = _UNRESOLVED

    def embed_path(self) -> str | None:
        if self._embed_path is _UNRESOLVED:
            cached = _EMBED_PATHS.get(self.id)
            if cached is not None and cached[0] == self.version:
                self._embed_path = cached[1]
                return self._embed_path
            if self.output_files_json is None:
                raise LookupError(f"embed path of {self.plugin} result {self.id} was not loaded for this list page")
            # Decode on first use: rendering asks only for the results it
            # shows (one per plugin, thumbnail candidates until one has a
            # file), so later hooks' and unused candidates' manifests stay text.
            output_files = json.loads(self.output_files_json)
            self._embed_path = ArchiveResult.resolve_embed_path(self.plugin, self.output_str, output_files or {})
            if len(_EMBED_PATHS) > _EMBED_PATHS_MAX:
                _EMBED_PATHS.clear()
            _EMBED_PATHS[self.id] = (self.version, self._embed_path)
        return self._embed_path


@dataclass(slots=True, eq=False)
class SnapshotListResults:
    """Everything list pages display about one snapshot's ArchiveResults."""

    # Results with a plugin, ordered by plugin then id (creation order).
    results: list[ListResult] = field(default_factory=list)
    # Legacy rows without a plugin only count towards admin progress totals.
    unnamed_status_counts: Counter[str] = field(default_factory=Counter)
    thumbnail_result: ArchiveResult | None = None

    @property
    def status_counts(self) -> Counter[str]:
        return Counter(result.status for result in self.results)

    @property
    def output_sizes(self) -> dict[str, int]:
        from archivebox.plugins.output_groups import plugin_output_sizes

        return plugin_output_sizes(self.results)

    def first_succeeded_by_plugin(self, *, with_output: bool = False) -> dict[str, ListResult]:
        """First successful result per plugin; optionally only results that saved bytes."""
        first: dict[str, ListResult] = {}
        for result in self.results:
            if result.status == ArchiveResult.StatusChoices.SUCCEEDED and (result.output_size > 0 or not with_output):
                first.setdefault(result.plugin, result)
        return first

    def succeeded_paths(self, plugins: set[str]) -> list[str]:
        """Embed paths of every successful result of these plugins, in result order."""
        return [
            output_path
            for result in self.results
            if result.plugin in plugins and result.status == ArchiveResult.StatusChoices.SUCCEEDED and (output_path := result.embed_path())
        ]


def load_snapshot_list_results(snapshots: Iterable[Any]) -> dict[Any, SnapshotListResults]:
    """Load a page of snapshots' results in one query, keyed by snapshot id.

    Embed paths and each snapshot's thumbnail card are resolved here, from the
    same rows, so rendering never queries per snapshot or per result.
    """
    from archivebox.plugins.discovery import get_snapshot_thumbnail_card_order
    from archivebox.plugins.output_groups import snapshot_thumbnail_result

    snapshots_by_hex = {snapshot.id.hex: snapshot for snapshot in snapshots}
    summaries = {snapshot_hex: SnapshotListResults() for snapshot_hex in snapshots_by_hex}
    if not summaries:
        return {}

    card_plugins = get_snapshot_thumbnail_card_order()
    # Successful results feed file icons and favicons; thumbnail cards try
    # their candidates regardless of status. Nothing else renders a path.
    links_output = Q(status=ArchiveResult.StatusChoices.SUCCEEDED) | Q(plugin__in=list(card_plugins))
    rows = (
        ArchiveResult.objects.filter(snapshot_id__in=[snapshot.id for snapshot in snapshots_by_hex.values()])
        # A stable order picks the same "first" result per plugin every time.
        .order_by("snapshot_id", "plugin", "id")
        .values_list(
            # Ids and manifests as text: the per-row UUID and JSON field
            # converters cost more than the rest of the page's row handling,
            # and most manifests are never decoded (see ListResult.embed_path).
            Cast("id", output_field=CharField()),
            Cast("snapshot_id", output_field=CharField()),
            "plugin",
            "status",
            "output_size",
            "output_str",
            Cast("modified_at", output_field=CharField()),
            # Whether this row can render a link (and so may need its manifest).
            Case(When(links_output, then=Value(True)), default=Value(False), output_field=BooleanField()),
        )
    )
    needs_manifest: dict[str, ListResult] = {}
    for result_id, snapshot_id, plugin, status, output_size, output_str, modified_at, links in rows:
        # PostgreSQL renders uuid as text with dashes; SQLite stores bare hex.
        summary = summaries[snapshot_id.replace("-", "")]
        if not plugin:
            summary.unnamed_status_counts[status] += 1
            continue
        result = ListResult(
            result_id.replace("-", ""),
            snapshot_id.replace("-", ""),
            plugin,
            status,
            output_size or 0,
            output_str,
            (modified_at, output_size, status),
        )
        summary.results.append(result)
        cached = _EMBED_PATHS.get(result.id)
        if links and (cached is None or cached[0] != result.version):
            needs_manifest[result.id] = result
    if needs_manifest:
        # Manifests only for linkable rows whose path is not cached yet.
        manifests = ArchiveResult.objects.filter(id__in=[compact_uuid(result_id) for result_id in needs_manifest]).values_list(
            Cast("id", output_field=CharField()),
            Cast("output_files", output_field=TextField()),
        )
        for result_id, output_files_json in manifests:
            result = needs_manifest[result_id.replace("-", "")]
            result.output_files_json = output_files_json
            # Resolve now, so the next view finds every fetched row cached even
            # when this one never rendered it (hidden icons, unused thumbnails).
            result.embed_path()

    for snapshot_hex, summary in summaries.items():
        card_row = snapshot_thumbnail_result(summary.results)
        if card_row is not None:
            summary.thumbnail_result = _archive_result_from_row(card_row)
            # Card URLs may read result.snapshot; share the page's loaded parent.
            summary.thumbnail_result.snapshot = snapshots_by_hex[snapshot_hex]
    return {snapshot.id: summaries[snapshot_hex] for snapshot_hex, snapshot in snapshots_by_hex.items()}


def _archive_result_from_row(row: ListResult) -> ArchiveResult:
    """Build the deferred ArchiveResult a ``.only()`` query would have loaded.

    Card rendering requires a real ArchiveResult; one per snapshot is cheap.
    """
    values = {
        "id": compact_uuid(row.id),
        "snapshot_id": compact_uuid(row.snapshot_id),
        "plugin": row.plugin,
        "status": row.status,
        "output_size": row.output_size,
        "output_str": row.output_str,
    }
    return ArchiveResult.from_db(
        connection.alias,
        list(values),
        [values.get(model_field.attname, DEFERRED) for model_field in ArchiveResult._meta.concrete_fields],
    )
