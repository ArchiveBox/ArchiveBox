"""ArchiveResult summaries for snapshot list pages.

The public index and the admin snapshot changelist show, per snapshot:
progress counts, per-plugin sizes, one file icon per successful plugin
(linking to that result's embed path), a favicon and a thumbnail.

Loading every result as a model instance with its ``output_files`` manifest
used to dominate these pages: model construction (field converters, signals,
descriptors) for every row, plus decoding manifests nothing renders. Here:

- every result is one plain value row, never a model instance;
- single-result plugin sizes come from the materialized ``output_size`` column;
- multi-hook plugin sizes deduplicate their shared manifest paths;
- the same query ships ``output_files`` as text for links, thumbnail candidates
  and multi-hook groups. Other rows never transfer theirs. Manifests are decoded
  only when rendering needs a link or must deduplicate a plugin's file sizes.

List pages must never read the archive filesystem; nothing here does.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.db import connection
from django.db.models import Case, CharField, Exists, OuterRef, Q, TextField, Value, When
from django.db.models.functions import Cast
from django.db.models.base import DEFERRED

from archivebox.core.models import ArchiveResult
from archivebox.uuid_compat import compact_uuid

if TYPE_CHECKING:
    from collections.abc import Iterable


_UNRESOLVED = object()


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
    # Undecoded JSON for link resolution and multi-hook size deduplication.
    output_files_json: str | None = None
    _embed_path: Any = _UNRESOLVED
    _output_files: dict[str, dict[str, Any]] | None = None

    def output_file_map(self) -> dict[str, dict[str, Any]]:
        if self._output_files is None:
            if self.output_files_json is None:
                raise LookupError(f"output files of {self.plugin} result {self.id} were not loaded for this list page")
            self._output_files = json.loads(self.output_files_json) or {}
        return self._output_files

    def embed_path(self) -> str | None:
        if self._embed_path is _UNRESOLVED:
            self._embed_path = ArchiveResult.resolve_embed_path(self.plugin, self.output_str, self.output_file_map())
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
        # Probe the existing (snapshot, plugin, hook) index only when needed.
        # A window count sorted/copied the large manifests for the entire page;
        # EXISTS avoids that work and stops at the first sibling hook.
        .alias(
            has_sibling_result=Exists(
                ArchiveResult.objects.filter(snapshot_id=OuterRef("snapshot_id"), plugin=OuterRef("plugin")).exclude(id=OuterRef("id")),
            ),
        )
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
            Case(
                When(links_output | Q(has_sibling_result=True), then=Cast("output_files", output_field=TextField())),
                default=Value(None),
                output_field=TextField(),
            ),
        )
    )
    for result_id, snapshot_id, plugin, status, output_size, output_str, output_files_json in rows:
        # PostgreSQL renders uuid as text with dashes; SQLite stores bare hex.
        summary = summaries[snapshot_id.replace("-", "")]
        if not plugin:
            summary.unnamed_status_counts[status] += 1
            continue
        summary.results.append(
            ListResult(
                result_id.replace("-", ""),
                snapshot_id.replace("-", ""),
                plugin,
                status,
                output_size or 0,
                output_str,
                output_files_json,
            ),
        )

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
