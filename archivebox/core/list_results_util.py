"""ArchiveResult summaries for snapshot list pages.

The public index and the admin snapshot changelist show, per snapshot:
progress counts, per-plugin sizes, one file icon per successful plugin
(linking to that result's embed path), a favicon and a thumbnail.

Loading every result as a model instance with its ``output_files`` manifest
used to dominate these pages: model construction (field converters, signals,
descriptors) for every row, plus decoding manifests nothing renders. Here:

- every result is one plain value row, never a model instance;
- sizes come from the materialized ``output_size`` column;
- the same query ships ``output_files`` only for rows that can render a link
  (successful results and thumbnail candidates); queued/failed/skipped rows
  never transfer or decode theirs.

List pages must never read the archive filesystem; nothing here does.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.db import connection
from django.db.models import Case, F, JSONField, Q, Value, When
from django.db.models.base import DEFERRED

from archivebox.core.models import ArchiveResult

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID


_UNRESOLVED = object()


@dataclass(slots=True, eq=False)
class ListResult:
    """One ArchiveResult as list pages read it: a value row, not a model instance.

    Duck-types the attributes and ``embed_path()`` that icon, favicon and
    thumbnail rendering read from ArchiveResult instances.
    """

    id: UUID
    snapshot_id: UUID
    plugin: str
    status: str
    output_size: int
    output_str: str
    _embed_path: Any = _UNRESOLVED

    def embed_path(self) -> str | None:
        if self._embed_path is _UNRESOLVED:
            # Only rows that can render a link carry their manifest (see below).
            raise LookupError(f"embed path of {self.plugin} result {self.id} was not loaded for this list page")
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
            if result.plugin in plugins
            and result.status == ArchiveResult.StatusChoices.SUCCEEDED
            and (output_path := result.embed_path())
        ]


def load_snapshot_list_results(snapshots: Iterable[Any]) -> dict[Any, SnapshotListResults]:
    """Load a page of snapshots' results in one query, keyed by snapshot id.

    Embed paths and each snapshot's thumbnail card are resolved here, from the
    same rows, so rendering never queries per snapshot or per result.
    """
    from archivebox.plugins.discovery import get_snapshot_thumbnail_card_order
    from archivebox.plugins.output_groups import snapshot_thumbnail_result

    snapshots_by_id = {snapshot.id: snapshot for snapshot in snapshots}
    summaries = {snapshot_id: SnapshotListResults() for snapshot_id in snapshots_by_id}
    if not summaries:
        return summaries

    card_plugins = get_snapshot_thumbnail_card_order()
    # Successful results feed file icons and favicons; thumbnail cards try
    # their candidates regardless of status. Nothing else renders a path.
    links_output = Q(status=ArchiveResult.StatusChoices.SUCCEEDED) | Q(plugin__in=list(card_plugins))
    rows = (
        ArchiveResult.objects.filter(snapshot_id__in=list(summaries))
        # A stable order picks the same "first" result per plugin every time.
        .order_by("snapshot_id", "plugin", "id")
        .values_list(
            "id",
            "snapshot_id",
            "plugin",
            "status",
            "output_size",
            "output_str",
            Case(When(links_output, then=F("output_files")), default=Value(None), output_field=JSONField()),
        )
    )
    for result_id, snapshot_id, plugin, status, output_size, output_str, output_files in rows:
        summary = summaries[snapshot_id]
        if not plugin:
            summary.unnamed_status_counts[status] += 1
            continue
        result = ListResult(result_id, snapshot_id, plugin, status, output_size or 0, output_str)
        if status == ArchiveResult.StatusChoices.SUCCEEDED or plugin in card_plugins:
            # Capture/import persist the canonical output_files map; resolve
            # straight from it, as embed_path_db() would on a model instance.
            result._embed_path = ArchiveResult.resolve_embed_path(plugin, output_str, output_files or {})
        summary.results.append(result)

    for snapshot_id, summary in summaries.items():
        card_row = snapshot_thumbnail_result(summary.results)
        if card_row is not None:
            summary.thumbnail_result = _archive_result_from_row(card_row)
            # Card URLs may read result.snapshot; share the page's loaded parent.
            summary.thumbnail_result.snapshot = snapshots_by_id[snapshot_id]
    return summaries


def _archive_result_from_row(row: ListResult) -> ArchiveResult:
    """Build the deferred ArchiveResult a ``.only()`` query would have loaded.

    Card rendering requires a real ArchiveResult; one per snapshot is cheap.
    """
    values = {
        "id": row.id,
        "snapshot_id": row.snapshot_id,
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
