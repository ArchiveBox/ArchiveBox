__package__ = "archivebox.search"

import json
from copy import copy
from subprocess import CalledProcessError
from types import SimpleNamespace
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db.models import Case, IntegerField, Q, QuerySet, Value, When

from archivebox.config.common import ArchiveBoxBaseConfig, get_config
from archivebox.misc.logging import stderr
from archivebox.misc.util import enforce_types, equivalent_urls
from archivebox.search.backends import get_available_backends, get_backend, search_backend_command_env
from archivebox.search.config import get_search_mode, get_search_mode_backend, get_search_mode_base

MAX_SEARCH_RANK_IDS = 500
SNAPSHOT_PROVENANCE_SCOPES = ("persona", "importer", "crawl_schedule", "crawl")


def require_snapshot_provenance_permissions(provenance, *, user, request=None):
    """Match native admin visibility, including for deferred export workers."""
    selected = {key for key in SNAPSHOT_PROVENANCE_SCOPES if provenance.get(key)}
    if not selected or user is None:
        return
    if not (user.is_active and user.is_staff):
        raise PermissionDenied
    if "persona" in selected:
        from archivebox.core.admin_site import archivebox_admin
        from archivebox.personas.models import Persona

        principal = copy(request) if request is not None else SimpleNamespace()
        principal.user = user
        if not archivebox_admin.is_registered(Persona) or not archivebox_admin.get_model_admin(Persona).has_view_or_change_permission(
            principal,
        ):
            raise PermissionDenied
    if "importer" in selected and not user.is_superuser:
        raise PermissionDenied
    if selected.intersection(("crawl_schedule", "crawl")) and not all(
        user.has_perm(f"crawls.view_{model}") or user.has_perm(f"crawls.change_{model}") for model in ("crawl", "crawlschedule")
    ):
        raise PermissionDenied


def apply_snapshot_filters(
    queryset,
    *,
    domain=None,
    domain_search=None,
    site_scopes=(),
    folder_id=None,
    provenance=None,
    status=None,
    archive_state=None,
    size=None,
    archiveresult_status=None,
):
    """Apply collection predicates shared by admin filters, exports, API and CLI."""
    from django.db.models import Count, Exists, F, OuterRef
    from archivebox.core.models import ArchiveResult, Folder
    from archivebox.core.snapshot_status import filter_snapshots_by_status

    if domain:
        queryset = queryset.filter_by_domain(domain)
    if site_scopes:
        from archivebox.domains.scope import site_snapshot_q

        queryset = queryset.filter(site_snapshot_q(site_scopes))
    if domain_search is not None:
        queryset = queryset.filter_by_domain_search(domain_search)
    if folder_id == "unfiled":
        queryset = queryset.filter(folder__isnull=True)
    elif folder_id:
        if not Folder.objects.filter(pk=folder_id).exists():
            raise ValueError("Folder does not exist.")
        queryset = queryset.in_folder(folder_id)
    if provenance:
        if crawl_id := provenance.get("crawl"):
            queryset = queryset.filter(crawl_id=crawl_id)
        crawl_filters = {
            field: value
            for param, field in (("persona", "persona_id"), ("crawl_schedule", "schedule_id"))
            if (value := provenance.get(param))
        }
        if crawl_filters:
            from archivebox.crawls.models import Crawl

            crawls = Crawl.objects.using(queryset.db).filter(**crawl_filters).order_by().values("pk")
            queryset = queryset.filter(crawl_id__in=crawls)
        if importer_id := provenance.get("importer"):
            from archivebox.importers.models import ImporterRun

            # ImporterSource.persona/name can change. Only ImporterRun.crawl
            # records actual origin; a semijoin also avoids duplicate rows.
            crawl_ids = (
                ImporterRun.objects.using(queryset.db)
                .filter(source_id=importer_id, action=ImporterRun.Action.IMPORT, crawl_id__isnull=False)
                .order_by()
                .values("crawl_id")
            )
            queryset = queryset.filter(crawl_id__in=crawl_ids)
    queryset = filter_snapshots_by_status(queryset, status)
    if archive_state == "downloaded":
        queryset = queryset.filter(downloaded_at__isnull=False)
    elif archive_state == "not_downloaded":
        queryset = queryset.filter(downloaded_at__isnull=True)
    elif archive_state == "has_output":
        queryset = queryset.filter(output_size__gt=0)
    elif archive_state == "empty_output":
        queryset = queryset.filter(output_size=0)
    elif archive_state == "has_title":
        queryset = queryset.exclude(Q(title__isnull=True) | Q(title=""))
    elif archive_state == "missing_title":
        queryset = queryset.filter(Q(title__isnull=True) | Q(title=""))
    thresholds = {"1gb": 1024**3, **{f"{amount}mb": amount * 1024**2 for amount in (500, 250, 100, 50, 25)}}
    if size in thresholds:
        queryset = queryset.filter(output_size__gt=thresholds[size])
    if archiveresult_status:
        results = ArchiveResult.objects.filter(snapshot_id=OuterRef("pk"))
        if archiveresult_status in {"none", "has_results"}:
            return queryset.annotate(has_results=Exists(results)).filter(has_results=archiveresult_status == "has_results")
        statuses = {
            "succeeded": ArchiveResult.StatusChoices.SUCCEEDED,
            "failed": ArchiveResult.StatusChoices.FAILED,
            "running": ArchiveResult.StatusChoices.STARTED,
            "pending": (ArchiveResult.StatusChoices.QUEUED, ArchiveResult.StatusChoices.BACKOFF),
            "backoff": ArchiveResult.StatusChoices.BACKOFF,
            "noresults": ArchiveResult.StatusChoices.NORESULTS,
        }
        if archiveresult_status in statuses:
            result_status = statuses[archiveresult_status]
            if archiveresult_status == "succeeded":
                # Successful captures dominate large collections. Probe each snapshot
                # through the covering index so a page can stop at its first matches.
                matching = (
                    results.order_by()
                    .values("snapshot_id")
                    .annotate(
                        total_results=Count("snapshot_id"),
                        matching_results=Count("snapshot_id", filter=Q(status=result_status)),
                    )
                    .filter(matching_results__gt=F("total_results") / 2)
                )
                return queryset.filter(Exists(matching))
            # Rare states benefit from finding candidate snapshots by status first.
            return queryset.filter(pk__in=ArchiveResult.snapshot_ids_with_majority_status(result_status))
    return queryset


def escape_like_query(query: str) -> str:
    """Escape a string for SQL LIKE matching (used with ESCAPE '\\')."""
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def crawl_config_values_search_wave(query: str, *, crawl_ids=None) -> Q | None:
    """Build a Snapshot Q predicate matching values inside Crawl.config."""
    from archivebox.crawls.models import Crawl

    pattern = f"%{escape_like_query(query).lower()}%"
    crawls = Crawl.objects.all()
    if crawl_ids is not None:
        crawls = crawls.filter(pk__in=crawl_ids)
    if connection.vendor == "sqlite":
        matching_crawls = crawls.extra(
            where=[
                """
                EXISTS (
                    SELECT 1
                    FROM json_tree(config)
                    WHERE json_tree.atom IS NOT NULL
                      AND LOWER(CAST(json_tree.atom AS TEXT)) LIKE %s ESCAPE '\\'
                )
                """,
            ],
            params=[pattern],
        )
    elif connection.vendor == "postgresql":
        # Match only scalar config *values*, not keys (mirrors SQLite's
        # json_tree.atom). jsonb_path_query('$.**') walks every nested node;
        # keep the non-container leaves and compare their text form.
        matching_crawls = crawls.extra(
            where=[
                """
                EXISTS (
                    SELECT 1
                    FROM jsonb_path_query(config, '$.**') AS leaf
                    WHERE jsonb_typeof(leaf) NOT IN ('object', 'array')
                      AND LOWER(leaf #>> '{}') LIKE %s ESCAPE '\\'
                )
                """,
            ],
            params=[pattern],
        )
    else:
        return None
    return Q(crawl_id__in=matching_crawls.values("pk"))


def url_search_q(query: str) -> Q:
    """Match URLs containing the query in any of its IRI/URI spellings.

    Snapshots keep URLs as submitted, so /über may be stored as /%C3%BCber
    (or the reverse); searching either spelling must find both.
    """
    url_q = Q()
    for variant in equivalent_urls(query):
        url_q |= Q(url__icontains=variant)
    return url_q


def snapshot_metadata_search_waves(query: str, *, include_id_matches: bool = False) -> list[Q]:
    """Build ordered metadata predicates for Snapshot search."""
    waves = []
    if include_id_matches:
        waves.append(Q(id__istartswith=query) | Q(id__iendswith=query))

    waves.extend(
        [
            Q(title__icontains=query) | url_search_q(query) | Q(timestamp__icontains=query),
            Q(tags__name__icontains=query),
            Q(notes__icontains=query) | Q(crawl__notes__icontains=query) | Q(crawl__label__icontains=query),
            Q(crawl__created_by__username=query),
        ],
    )

    config_wave = crawl_config_values_search_wave(query)
    if config_wave is not None:
        waves.append(config_wave)
    return waves


def prioritize_metadata_matches(
    base_queryset: QuerySet,
    metadata_queryset: QuerySet,
    fulltext_queryset: QuerySet,
    *,
    ordering: list[str] | tuple[str, ...] | None = None,
) -> QuerySet:
    """Rank metadata hits before backend full-text hits."""
    metadata_ids = list(metadata_queryset.values_list("pk", flat=True).distinct()[: MAX_SEARCH_RANK_IDS + 1])
    metadata_id_set = set(metadata_ids)
    fulltext_ids = [
        pk for pk in fulltext_queryset.values_list("pk", flat=True).distinct()[: MAX_SEARCH_RANK_IDS + 1] if pk not in metadata_id_set
    ]
    if not metadata_ids and not fulltext_ids:
        return base_queryset.none()

    if any(len(ids) > MAX_SEARCH_RANK_IDS for ids in (metadata_ids, fulltext_ids)):
        search_filter = Q()
        if metadata_ids:
            search_filter |= Q(pk__in=metadata_queryset.values("pk").distinct())
        if fulltext_ids:
            search_filter |= Q(pk__in=fulltext_queryset.values("pk").distinct())
        qs = base_queryset.filter(search_filter)
        if ordering is not None:
            qs = qs.order_by(*ordering)
        return qs.distinct()

    qs = base_queryset.filter(pk__in=[*metadata_ids, *fulltext_ids]).annotate(
        search_rank=Case(
            When(pk__in=metadata_ids, then=Value(0)),
            When(pk__in=fulltext_ids, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        ),
    )

    if ordering is not None:
        qs = qs.order_by("search_rank", *ordering)

    return qs.distinct()


def apply_snapshot_search(
    base_queryset: QuerySet,
    query: str,
    *,
    search_mode: str | None = None,
    config: ArchiveBoxBaseConfig | dict[str, Any] | None = None,
    ordering: list[str] | tuple[str, ...] | None = None,
    max_results: int | None = None,
    skip_backend_when_metadata_satisfies_limit: bool = False,
    public: bool = False,
    include_metadata_for_forced_backend: bool = False,
    include_id_matches: bool = False,
) -> QuerySet:
    """Apply shared CLI/API/public/admin Snapshot search semantics."""
    query = (query or "").strip()
    if not query:
        return base_queryset

    if not search_mode or search_mode == "query":
        from archivebox.search.interpreter import SnapshotSearch

        return SnapshotSearch(base_queryset, query, config=config, public=public).queryset()

    config = config or get_config()
    search_mode = get_search_mode(search_mode, config=config)
    search_mode_base = get_search_mode_base(search_mode, config=config)
    search_mode_backend = get_search_mode_backend(search_mode, config=config)
    if search_mode_base == "url":
        return base_queryset.filter(url_search_q(query))
    metadata_filter = Q()
    for wave in snapshot_metadata_search_waves(query, include_id_matches=include_id_matches):
        metadata_filter |= wave
    metadata_queryset = base_queryset.filter(metadata_filter)

    if search_mode_base == "meta":
        return metadata_queryset.distinct()

    if skip_backend_when_metadata_satisfies_limit and max_results:
        metadata_ids = list(metadata_queryset.values_list("pk", flat=True).distinct()[:max_results])
        if len(metadata_ids) >= max_results:
            return metadata_queryset.distinct()

    backend_queryset = query_search_index(query, search_mode=search_mode, config=config, max_results=max_results, scope=base_queryset)
    if search_mode_backend and not include_metadata_for_forced_backend:
        return base_queryset.filter(pk__in=backend_queryset.values("pk")).distinct()

    return prioritize_metadata_matches(
        base_queryset,
        metadata_queryset,
        backend_queryset,
        ordering=ordering,
    )


@enforce_types
def query_search_index(
    query: str,
    search_mode: str | None = None,
    config: ArchiveBoxBaseConfig | dict[str, Any] | None = None,
    max_results: int | None = None,
    scope: QuerySet | None = None,
    **config_kwargs: Any,
) -> QuerySet:
    """Return a Snapshot queryset from backend search IDs."""
    from archivebox.core.models import Snapshot

    config = config or get_config(**config_kwargs)
    search_mode = "contents" if search_mode is None else get_search_mode(search_mode, config=config)
    search_mode_base = get_search_mode_base(search_mode, config=config)
    if search_mode_base == "meta":
        return Snapshot.objects.none()

    snapshot_pks = list(iter_query_search_ids(query, search_mode=search_mode, config=config, max_results=max_results, scope=scope))
    return Snapshot.objects.filter(pk__in=list(dict.fromkeys(snapshot_pks)))


def iter_query_search_ids(
    query: str,
    search_mode: str | None = None,
    config: ArchiveBoxBaseConfig | dict[str, Any] | None = None,
    max_results: int | None = None,
    scope: QuerySet | None = None,
    stop_event=None,
    progress=None,
    **config_kwargs: Any,
):
    """Yield snapshot IDs from configured search backend modules."""
    config = config or get_config(**config_kwargs)
    search_mode = "contents" if search_mode is None else get_search_mode(search_mode, config=config)
    search_mode_base = get_search_mode_base(search_mode, config=config)
    forced_backend = get_search_mode_backend(search_mode, config=config)
    if search_mode_base == "url":
        from archivebox.core.models import Snapshot

        yield from Snapshot.objects.filter(url_search_q(query.strip())).values_list("pk", flat=True)[:max_results].iterator()
        return
    if search_mode_base == "meta":
        return

    backend = get_available_backends(config)[forced_backend] if forced_backend else get_backend(config=config)
    if not backend:
        return
    if backend.config.search_scan:
        from itertools import islice
        from archivebox.core.models import Snapshot
        from archivebox.search.interpreter import SnapshotSearch

        # Old contents links and CLI/API callers must respect the same scope and
        # total budget as an operator query. Never invoke a whole-archive scan.
        search = SnapshotSearch(
            scope if scope is not None else Snapshot.objects.all(),
            json.dumps(query),
            config=config,
            stop_event=stop_event,
            streaming=True,
            progress=progress,
        )
        yield from islice(search.scan_content_ids(backend), max_results)
        return
    from archivebox.plugins.services import ensure_plugin_services
    from archivebox.plugins.discovery import get_plugin_catalog
    from archivebox.config.constants import CONSTANTS
    from abx_dl.execution import iter_plugin_command
    from contextlib import redirect_stdout
    import sys

    try:
        with redirect_stdout(sys.stderr):
            ensure_plugin_services(config, plugin_names={backend.name}, reason="search query")
        command = get_plugin_catalog().command(backend.name, "search")
        if command is None:
            raise RuntimeError(f'Plugin "{backend.name}" does not expose a search command')
        limit = max(1, int(config.get("TIMEOUT", 60))) * 4
        ids = iter_plugin_command(
            command,
            arguments={"query": query, "search_mode": "contents"},
            env=search_backend_command_env(config=config),
            cwd=CONSTANTS.DATA_DIR,
            timeout=limit,
            stop_event=stop_event,
        )
        if progress:
            ids = progress.reading(ids, "provider", backend.name, timeout=limit)
        seen = set()
        try:
            for snapshot_id in ids:
                if snapshot_id not in seen:
                    seen.add(snapshot_id)
                    yield snapshot_id
                    if max_results and len(seen) >= max_results:
                        break
        finally:
            ids.close()
    except Exception as err:
        stderr()
        stderr(
            f"[X] The search backend threw an exception={err}:",
            color="red",
        )
        if isinstance(err, CalledProcessError) and err.stderr:
            stderr(err.stderr.rstrip(), color="red")
        raise


@enforce_types
def flush_search_index(snapshots: QuerySet, config: ArchiveBoxBaseConfig | dict[str, Any] | None = None, **config_kwargs: Any) -> None:
    """Remove Snapshot IDs from the configured search backend index."""
    config = config or get_config(**config_kwargs)
    if not snapshots:
        return

    backend = get_backend(config=config)
    if not backend or backend.config.search_scan:
        return
    snapshot_pks = [str(pk) for pk in snapshots.values_list("pk", flat=True)]

    try:
        from abx_dl.execution import iter_plugin_command
        from archivebox.config.constants import CONSTANTS
        from archivebox.plugins.discovery import get_plugin_catalog

        command = get_plugin_catalog().command(backend.name, "flush")
        if command is None:
            raise RuntimeError(f'Plugin "{backend.name}" does not expose a flush command')
        list(
            iter_plugin_command(
                command,
                stdin=snapshot_pks,
                env=search_backend_command_env(config=config),
                cwd=CONSTANTS.DATA_DIR,
                timeout=max(1, int(config.get("TIMEOUT", 60))) * 4,
            ),
        )
    except Exception as err:
        stderr()
        stderr(
            f"[X] The search backend threw an exception={err}:",
            color="red",
        )
