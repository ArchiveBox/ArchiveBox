__package__ = "archivebox.search"

from django.contrib import admin
from django.contrib.admin.views.main import ChangeList
from django.db.models import Case, IntegerField, Value, When

from archivebox.search.config import (
    get_default_search_mode,
    get_search_mode,
    get_search_mode_backend,
    get_search_mode_base,
    get_search_mode_options,
)
from archivebox.search.query import query_search_index
from archivebox.search.views import get_cached_admin_search_ids


class SearchResultsChangeList(ChangeList):
    """Django admin ChangeList with ArchiveBox search mode state."""

    def __init__(self, request, *args, **kwargs):
        """Capture normalized search mode before Django builds results."""
        self.search_mode = get_search_mode(request.GET.get("search_mode"), config=request.archivebox_config)
        self.search_mode_backend = get_search_mode_backend(self.search_mode, config=request.archivebox_config)
        super().__init__(request, *args, **kwargs)
        self.embedded_changelist = request.GET.get("_embedded") == "crawl"

    def get_results(self, request):
        """Populate normal admin results plus search-index hint state."""
        super().get_results(request)
        self.show_search_index_hint = bool(
            self.opts.model_name == "snapshot"
            and self.query
            and self.result_count == 0
            and get_search_mode_base(self.search_mode, config=request.archivebox_config) == "deep"
            and self.search_mode_backend,
        )

    def get_filters_params(self, params=None):
        """Remove UI-only search params before admin filter processing."""
        lookup_params = super().get_filters_params(params)
        lookup_params.pop("search_mode", None)
        lookup_params.pop("_embedded", None)
        lookup_params.pop("per_page", None)
        return lookup_params


class SearchResultsAdminMixin(admin.ModelAdmin):
    """Mixin that routes admin searches through ArchiveBox search modes."""

    show_search_mode_selector = True

    def get_changelist(self, request, **kwargs):
        """Return the ArchiveBox search-aware ChangeList class."""
        return SearchResultsChangeList

    def get_default_search_mode(self):
        """Return the default search mode for the current request config."""
        return get_default_search_mode(config=self.request.archivebox_config)

    def get_search_mode_options(self):
        """Return selector options for the current request config."""
        return get_search_mode_options(config=self.request.archivebox_config)

    def get_search_results(self, request, queryset, search_term: str):
        """Apply admin search semantics to a changelist queryset."""

        search_term = search_term.strip()
        if not search_term:
            return super().get_search_results(request, queryset, search_term)
        search_mode = get_search_mode(request.GET.get("search_mode"), config=request.archivebox_config)
        if queryset.model._meta.label_lower == "core.snapshot" and request.GET.get("_embedded") != "crawl":
            cached_ids = get_cached_admin_search_ids(request)
            if cached_ids is not None:
                if not cached_ids:
                    return queryset.none(), False
                search_rank = Case(
                    *(When(pk=snapshot_id, then=Value(index)) for index, snapshot_id in enumerate(cached_ids)),
                    output_field=IntegerField(),
                )
                return queryset.filter(pk__in=cached_ids).annotate(search_rank=search_rank).order_by("search_rank"), False
            return queryset.none(), False

        if get_search_mode_base(search_mode, config=request.archivebox_config) == "meta":
            qs, use_distinct = super().get_search_results(request, queryset, search_term)
            return qs, use_distinct
        if request.GET.get("_embedded") == "crawl":
            try:
                return queryset.filter(
                    pk__in=query_search_index(
                        search_term,
                        search_mode=search_mode,
                        config=request.archivebox_config,
                    ).values("pk"),
                ), False
            except Exception as err:
                print(f"[!] Error while using search backend: {err.__class__.__name__} {err}")
                return queryset.none(), False
        return queryset.none(), False
