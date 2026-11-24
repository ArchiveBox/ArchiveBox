"""ArchiveResult summaries for snapshot list pages.

The public index and the admin snapshot changelist show, per snapshot:
progress counts, per-plugin sizes, one file icon per successful plugin
(linking to its detail card), a favicon and a thumbnail.

Loading every result as a model instance with its ``output_files`` manifest
used to dominate these pages: model construction (field converters, signals,
descriptors) for every row, plus decoding manifests nothing renders. Here:

- every result is one plain value row, never a model instance;
- single-result plugin sizes come from the materialized ``output_size`` column;
- multi-hook plugin sizes deduplicate their shared manifest paths;
- the same query ships ``output_files`` as text for favicons, thumbnail candidates
  and multi-hook groups. Plugin icons link to detail cards using status and stored
  size and a database existence check, without resolving a file. Other rows
  never transfer their manifests.
- SQLite and PostgreSQL project explicit thumbnail/favicon paths to one metadata entry;
  shared-file size deduplication and fallback path selection keep full manifests.

List pages must never read the archive filesystem; nothing here does.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.db import connection
from django.db.models import BooleanField, Case, CharField, Exists, Func, IntegerField, OuterRef, Q, TextField, Value, When
from django.db.models.functions import Cast
from django.db.models.base import DEFERRED

from archivebox.core.models import ArchiveResult
from archivebox.core.routes_util import build_snapshot_url
from archivebox.plugins.discovery import get_snapshot_role_names
from archivebox.uuid_compat import compact_uuid

if TYPE_CHECKING:
    from collections.abc import Iterable


_UNRESOLVED = object()


class _LinkManifest(Func):
    """Project an explicit output path; preserve the full manifest for fallback."""

    output_field = TextField()
    _whitespace = " \t\n\r\v\f\x1c\x1d\x1e\x1f\x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"

    def as_sql(self, compiler, connection, **extra_context):
        return compiler.compile(Cast(self.source_expressions[0], output_field=TextField()))

    def as_sqlite(self, compiler, connection, **extra_context):
        manifest, manifest_params = compiler.compile(self.source_expressions[0])
        plugin, plugin_params = compiler.compile(self.source_expressions[1])
        output, output_params = compiler.compile(self.source_expressions[2])
        # Match str.strip(), exact-key precedence and the resolver's traversal
        # rejection. Text-output plugins and shared-file sizes bypass projection.
        raw_path = "'$.' || json_quote(raw)"
        alternate = "substr(raw, length(prefix) + 1)"
        alternate_path = f"'$.' || json_quote({alternate})"
        sql = f"""(SELECT CASE
            WHEN substr(raw, 1, length(prefix)) = prefix
                AND length(raw) > length(prefix)
                AND instr('/' || raw || '/', '/../') = 0 THEN CASE
                WHEN json_type({manifest}, {raw_path}) = 'object'
                    THEN json_object(raw, json_extract({manifest}, {raw_path}))
                WHEN json_type({manifest}, {alternate_path}) = 'object'
                    THEN json_object({alternate}, json_extract({manifest}, {alternate_path}))
                ELSE {manifest} END
            ELSE {manifest} END
            FROM (SELECT trim({output}, %s) AS raw, {plugin} || '/' AS prefix LIMIT 1)
        )"""
        return sql, [*manifest_params * 6, *output_params, self._whitespace, *plugin_params]

    def as_postgresql(self, compiler, connection, **extra_context):
        manifest, manifest_params = compiler.compile(self.source_expressions[0])
        plugin, plugin_params = compiler.compile(self.source_expressions[1])
        output, output_params = compiler.compile(self.source_expressions[2])
        alternate = "substr(raw, length(prefix) + 1)"
        sql = f"""(SELECT CASE
            WHEN left(raw, length(prefix)) = prefix
                AND length(raw) > length(prefix)
                AND strpos('/' || raw || '/', '/../') = 0 THEN CASE
                WHEN jsonb_typeof({manifest} -> raw) = 'object'
                    THEN jsonb_build_object(raw, {manifest} -> raw)::text
                WHEN jsonb_typeof({manifest} -> {alternate}) = 'object'
                    THEN jsonb_build_object({alternate}, {manifest} -> {alternate})::text
                ELSE {manifest}::text END
            ELSE {manifest}::text END
            FROM (SELECT btrim({output}, %s) AS raw, {plugin} || '/' AS prefix LIMIT 1) AS paths
        )"""
        return sql, [*manifest_params * 6, *output_params, self._whitespace, *plugin_params]


class _HasSavedOutput(Func):
    """Stop at one saved file; hook scripts/logs alone are not captured output."""

    output_field = BooleanField(null=True)

    def _sql(self, compiler, iterator, object_check):
        manifest, params = compiler.compile(self.source_expressions[0])
        return (
            f"CASE WHEN {manifest} = '{{}}' THEN NULL ELSE EXISTS ("
            f"SELECT 1 FROM {iterator}({manifest}) AS files WHERE {object_check} "
            "AND LOWER(files.key) NOT LIKE %s AND LOWER(files.key) NOT LIKE %s AND LOWER(files.key) NOT LIKE %s) END",
            [*params, *params, "%.pid", "%.log", "%.sh"],
        )

    def as_sqlite(self, compiler, connection, **extra_context):
        manifest, params = compiler.compile(self.source_expressions[0])
        return f"archivebox_has_saved_output({manifest})", params

    def as_postgresql(self, compiler, connection, **extra_context):
        return self._sql(compiler, "jsonb_each", "jsonb_typeof(files.value) = 'object'")


def favicon_results():
    """Fetch only the archived outputs eligible to be favicons."""
    return (
        ArchiveResult.objects.filter(plugin__in=get_snapshot_role_names("list_icon"), status=ArchiveResult.StatusChoices.SUCCEEDED)
        .only("id", "snapshot_id", "plugin", "status", "output_str", "output_files")
        .order_by("plugin", "id")
    )


def snapshot_favicon_data(snapshot_id, results, *, request):
    icon_plugins = get_snapshot_role_names("list_icon")
    urls = []
    for result in results:
        if result.plugin not in icon_plugins or result.status != ArchiveResult.StatusChoices.SUCCEEDED:
            continue
        try:
            output_path = result.embed_path()
        except (TypeError, ValueError, OverflowError):
            continue
        if output_path:
            urls.append(build_snapshot_url(str(snapshot_id), output_path, request=request))
    return {"url": urls[0], "fallbacks": ",".join(urls[1:])} if urls else None


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
    has_saved_output: int | bool | None = None
    _embed_path: Any = _UNRESOLVED
    _output_files: dict[str, dict[str, Any]] | None = None
    _retain_output_files: bool = True

    def output_file_map(self) -> dict[str, dict[str, Any]]:
        if self._output_files is not None:
            return self._output_files
        if self.output_files_json is None:
            raise LookupError(f"output files of {self.plugin} result {self.id} were not loaded for this list page")
        output_files = json.loads(self.output_files_json) or {}
        if self._retain_output_files:
            self._output_files = output_files
        return output_files

    def embed_path(self) -> str | None:
        if self._embed_path is _UNRESOLVED:
            self._embed_path = ArchiveResult.resolve_embed_path(self.plugin, self.output_str, self.output_file_map())
        return self._embed_path

    def icon_anchor(self) -> str | None:
        from archivebox.plugins.discovery import get_plugin_name, plugin_output_is_text

        # Match the resolver's rejection of legacy absolute output paths.
        if self.output_str and not plugin_output_is_text(self.plugin) and self.output_str.strip().startswith("/"):
            return None
        if self.has_saved_output or (self.has_saved_output is None and ArchiveResult.resolve_embed_path(self.plugin, self.output_str, {})):
            return get_plugin_name(self.plugin)
        return None


@dataclass(slots=True, eq=False)
class SnapshotListResults:
    """Everything list pages display about one snapshot's ArchiveResults."""

    # Results with a plugin, ordered by plugin then id (creation order).
    results: list[ListResult] = field(default_factory=list)
    # Legacy rows without a plugin only count towards admin progress totals.
    unnamed_status_counts: Counter[str] = field(default_factory=Counter)
    thumbnail_result: ArchiveResult | None = None
    thumbnail_image_paths: tuple[tuple[str, str], ...] = ()

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


def load_snapshot_list_results(snapshots: Iterable[Any], *, images_only: bool = False) -> dict[Any, SnapshotListResults]:
    """Load a page of snapshots' results in one query, keyed by snapshot id.

    Embed paths and each snapshot's thumbnail card are resolved here, from the
    same rows, so rendering never queries per snapshot or per result.
    """
    from archivebox.plugins.discovery import get_snapshot_thumbnail_card_order, get_snapshot_thumbnail_image_names, plugin_output_is_text
    from archivebox.plugins.output_groups import snapshot_thumbnail_image_paths, snapshot_thumbnail_result

    snapshots_by_hex = {snapshot.id.hex: snapshot for snapshot in snapshots}
    summaries = {snapshot_hex: SnapshotListResults() for snapshot_hex in snapshots_by_hex}
    if not summaries:
        return {}

    card_plugins = get_snapshot_thumbnail_image_names(screenshots_only=True) if images_only else tuple(get_snapshot_thumbnail_card_order())
    # File icons open plugin cards, not individual files. Only favicons and
    # thumbnail candidates need a file path on a list page.
    links_output = Q(plugin__in=list(card_plugins)) | Q(
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        plugin__in=get_snapshot_role_names("list_icon"),
    )
    path_plugins = [name for name in set(card_plugins) | set(get_snapshot_role_names("list_icon")) if not plugin_output_is_text(name)]
    icon_results = Q(status=ArchiveResult.StatusChoices.SUCCEEDED)
    if images_only:
        # The admin only opens piles for outputs with stored bytes.
        icon_results &= Q(output_size__gt=0)
    rows = (
        ArchiveResult.objects.filter(snapshot_id__in=[snapshot.id for snapshot in snapshots_by_hex.values()])
        # A second hook is enough to require the full manifest. Skipping the
        # first index entry avoids reading a sibling row just to compare its id.
        .alias(
            has_sibling_result=Exists(
                ArchiveResult.objects.filter(snapshot_id=OuterRef("snapshot_id"), plugin=OuterRef("plugin"))[1:2],
            ),
        )
        # Avoid copying full manifests into a database sort. Sort the small
        # per-snapshot row references below to preserve first-result selection.
        .order_by()
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
                When(has_sibling_result=True, then=Cast("output_files", output_field=TextField())),
                # The admin may try another image from the same capture if its
                # primary image is unavailable. These captures have small manifests.
                When(plugin__in=list(card_plugins) if images_only else (), then=Cast("output_files", output_field=TextField())),
                When(links_output & Q(plugin__in=path_plugins), then=_LinkManifest("output_files", "plugin", "output_str")),
                When(links_output, then=Cast("output_files", output_field=TextField())),
                default=Value(None),
                output_field=TextField(),
            ),
            Cast(
                # The icon selector only needs truthiness and a distinct NULL
                # for legacy rows. Return that directly from both databases.
                Case(
                    When(icon_results, then=_HasSavedOutput("output_files")),
                    default=Value(False),
                    output_field=BooleanField(null=True),
                ),
                output_field=IntegerField(),
            ),
        )
    )
    for result_id, snapshot_id, plugin, status, output_size, output_str, output_files_json, has_saved_output in rows:
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
                has_saved_output,
            ),
        )

    for snapshot_hex, summary in summaries.items():
        summary.results.sort(key=lambda result: (result.plugin, result.id))
        plugin_counts = Counter(result.plugin for result in summary.results)
        for result in summary.results:
            # A single hook uses the stored size and caches its resolved link.
            # Only siblings reuse the parsed map to deduplicate shared files.
            result._retain_output_files = plugin_counts[result.plugin] > 1
        if images_only:
            summary.thumbnail_image_paths = tuple(snapshot_thumbnail_image_paths(summary.results, screenshots_only=True))
        elif (card_row := snapshot_thumbnail_result(summary.results)) is not None:
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
