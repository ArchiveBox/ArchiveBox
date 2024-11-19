__package__ = 'archivebox.search'

from django.contrib import messages
from django.contrib import admin

from archivebox.search import query_search_index

class SearchResultsAdminMixin(admin.ModelAdmin):
    def get_search_results(self, request, queryset, search_term: str):
        """Enhances the search queryset with results from the search backend"""
        
        qs, use_distinct = super().get_search_results(request, queryset, search_term)

        search_term = search_term.strip()
        if not search_term:
            return qs.distinct(), use_distinct
        try:
            qsearch = query_search_index(search_term)
            qs = qs | qsearch
        except Exception as err:
            print(f'[!] Error while using search backend: {err.__class__.__name__} {err}')
            messages.add_message(request, messages.WARNING, f'Error from the search backend, only showing results from default admin search fields - Error: {err}')
        
        return qs.distinct(), use_distinct
