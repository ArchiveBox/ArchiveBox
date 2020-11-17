from django.db.models import Q, Case, When, Value, IntegerField

from archivebox.search import search_index

class SearchResultsAdminMixin(object):
    def get_search_results(self, request, queryset, search_term):
        ''' Show exact match for title and slug at top of admin search results.
        '''
        qs, use_distinct = \
            super(SearchResultsAdminMixin, self).get_search_results(
                request, queryset, search_term)

        search_term = search_term.strip()
        if not search_term:
            return qs, use_distinct

        snapshot_ids = search_index(search_term)
        qsearch = queryset.filter(id__in=snapshot_ids)
        qs |= qsearch

        return qs, use_distinct