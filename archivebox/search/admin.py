__package__ = "archivebox.search"

from django.contrib import admin
from django.contrib.admin.views.main import ChangeList
from django.db.models import Case, Expression, IntegerField, Value, When

from archivebox.search.config import (
    get_search_mode,
    get_search_mode_backend,
    get_search_mode_base,
    get_search_mode_options,
)
from archivebox.search.query import query_search_index, url_search_q
from archivebox.search.views import get_cached_admin_search_state, ranked_page_ids


class CachedSearchRank(Expression):
    """Compile the full cached rank only when the complete queryset is ordered."""

    def __init__(self, ids):
        super().__init__(output_field=IntegerField())
        self.ids = tuple(ids)

    def as_sql(self, compiler, connection):
        rank = Case(
            *(When(pk=snapshot_id, then=Value(index)) for index, snapshot_id in enumerate(self.ids)),
            output_field=self.output_field,
        )
        return compiler.compile(rank.resolve_expression(compiler.query))


def cached_search_rank_page(request, *, start, size):
    """Read cached rank in bounded batches, rechecking the current filter scope."""
    scope = getattr(request, "_archivebox_search_rank_scope", None)
    if scope is None or "o" in request.GET:
        return None
    return ranked_page_ids(scope, request._archivebox_search_ranks, start=start, size=size)


class SearchResultsChangeList(ChangeList):
    """Django admin ChangeList with ArchiveBox search mode state."""

    def __init__(self, request, *args, **kwargs):
        """Capture normalized search mode before Django builds results."""
        self.search_mode = get_search_mode(request.GET.get("search_mode") or "query", config=request.archivebox_config)
        self.search_mode_backend = get_search_mode_backend(self.search_mode, config=request.archivebox_config)
        super().__init__(request, *args, **kwargs)
        self.embedded_changelist = request.GET.get("_embedded") == "crawl"
        self.search_stream_complete = bool(getattr(request, "_archivebox_search_complete", False))

    def get_results(self, request):
        """Populate normal admin results plus search-index hint state."""
        super().get_results(request)
        self.show_search_index_hint = bool(
            self.opts.model_name == "snapshot"
            and self.query
            and self.result_count == 0
            and get_search_mode_base(self.search_mode, config=request.archivebox_config) == "contents"
            and self.search_mode_backend,
        )

    def get_filters_params(self, params=None):
        """Remove UI-only search params before admin filter processing."""
        lookup_params = super().get_filters_params(params)
        lookup_params.pop("search_mode", None)
        lookup_params.pop("_embedded", None)
        lookup_params.pop("per_page", None)
        lookup_params.pop("_archivebox_select_all", None)
        return lookup_params


class SearchResultsAdminMixin(admin.ModelAdmin):
    """Mixin that routes admin searches through ArchiveBox search modes."""

    show_search_mode_selector = True

    def get_changelist(self, request, **kwargs):
        """Return the ArchiveBox search-aware ChangeList class."""
        return SearchResultsChangeList

    def get_default_search_mode(self):
        """Return the default search mode for the current request config."""
        return "query"

    def get_search_mode_options(self):
        """Return selector options for the current request config."""
        return get_search_mode_options(config=self.request.archivebox_config)

    def get_search_results(self, request, queryset, search_term: str):
        """Apply admin search semantics to a changelist queryset."""

        search_term = search_term.strip()
        if not search_term:
            return super().get_search_results(request, queryset, search_term)
        search_mode = get_search_mode(request.GET.get("search_mode") or "query", config=request.archivebox_config)
        if get_search_mode_base(search_mode, config=request.archivebox_config) == "url":
            request._archivebox_search_complete = True
            return queryset.filter(url_search_q(search_term)), False
        if queryset.model._meta.label_lower == "core.snapshot" and request.GET.get("_embedded") != "crawl":
            if search_mode == "query":
                from archivebox.search.interpreter import sql_snapshot_search

                filtered = sql_snapshot_search(queryset, search_term, ranked="o" not in request.GET)
                if filtered is not None:
                    request._archivebox_search_complete = True
                    return filtered, False
            state = get_cached_admin_search_state(request)
            request._archivebox_search_complete = bool(state and state.get("done"))
            if state is not None:
                cached_ids = state.get("ids") or []
                if not cached_ids:
                    return queryset.none(), False
                request._archivebox_search_ranks = {snapshot_id: index for index, snapshot_id in enumerate(cached_ids)}
                request._archivebox_search_rank_scope = queryset
                ranked = queryset.filter(pk__in=cached_ids).alias(search_rank=CachedSearchRank(cached_ids))
                return (ranked if "o" in request.GET else ranked.order_by("search_rank")), False
            return queryset.none(), False

        if get_search_mode_base(search_mode, config=request.archivebox_config) == "meta":
            qs, use_distinct = super().get_search_results(request, queryset, search_term)
            return qs, use_distinct
        if request.GET.get("_embedded") == "crawl":
            if search_mode == "query":
                from archivebox.search.query import apply_snapshot_search

                return apply_snapshot_search(queryset, search_term, config=request.archivebox_config), False
            try:
                return queryset.filter(
                    pk__in=query_search_index(
                        search_term,
                        search_mode=search_mode,
                        config=request.archivebox_config,
                        scope=queryset,
                    ).values("pk"),
                ), False
            except Exception as err:
                print(f"[!] Error while using search backend: {err.__class__.__name__} {err}")
                return queryset.none(), False
        return queryset.none(), False
