from django.contrib import messages

from archivebox.search import query_search_index

class SearchResultsAdminMixin(object):
    def get_search_results(self, request, queryset, search_term):
        ''' Enhances the search queryset with results from the search backend.
        '''
        qs, use_distinct = \
            super(SearchResultsAdminMixin, self).get_search_results(
                request, queryset, search_term)

        search_term = search_term.strip()
        if not search_term:
            return qs, use_distinct
        try:
            qsearch = query_search_index(search_term)
        except Exception as err:
            messages.add_message(request, messages.WARNING, f'Error from the search backend, only showing results from default admin search fields - Error: {err}')
        else:
            qs = queryset & qsearch
        finally:
            return qs, use_distinct
