__package__ = "archivebox.search"

from django.contrib import messages
from django.contrib import admin
from django.contrib.admin.views.main import ChangeList, ORDER_VAR

from archivebox.search import get_default_search_mode, get_search_mode, prioritize_metadata_matches, query_search_index


class SearchResultsChangeList(ChangeList):
    def get_filters_params(self, params=None):
        lookup_params = super().get_filters_params(params)
        lookup_params.pop("search_mode", None)
        return lookup_params


class SearchResultsAdminMixin(admin.ModelAdmin):
    show_search_mode_selector = True

    def get_changelist(self, request, **kwargs):
        return SearchResultsChangeList

    def get_default_search_mode(self):
        return get_default_search_mode()

    def get_search_results(self, request, queryset, search_term: str):
        """Enhances the search queryset with results from the search backend"""

        qs, use_distinct = super().get_search_results(request, queryset, search_term)

        search_term = search_term.strip()
        if not search_term:
            return qs.distinct(), use_distinct
        search_mode = get_search_mode(request.GET.get("search_mode"))
        if search_mode == "meta":
            return qs.distinct(), use_distinct
        try:
            deep_qsearch = None
            if search_mode == "deep":
                qsearch = query_search_index(search_term, search_mode="contents")
                deep_qsearch = query_search_index(search_term, search_mode="deep")
            else:
                qsearch = query_search_index(search_term, search_mode=search_mode)
            qs = prioritize_metadata_matches(
                queryset,
                qs,
                qsearch,
                deep_queryset=deep_qsearch,
                ordering=() if not request.GET.get(ORDER_VAR) else None,
            )
        except Exception as err:
            print(f"[!] Error while using search backend: {err.__class__.__name__} {err}")
            messages.add_message(
                request,
                messages.WARNING,
                f"Error from the search backend, only showing results from default admin search fields - Error: {err}",
            )

        return qs.distinct(), use_distinct
