__package__ = 'archivebox.misc'

from django.core.paginator import Paginator
from django.utils.functional import cached_property


class AccelleratedPaginator(Paginator):
    """
    Accellerated Pagniator ignores DISTINCT when counting total number of rows.
    Speeds up SELECT Count(*) on Admin views by >20x.
    https://hakibenita.com/optimizing-the-django-admin-paginator
    """

    @cached_property
    def count(self):
        if self.object_list._has_filters():                             # type: ignore
            # fallback to normal count method on filtered queryset
            return super().count
        else:
            # otherwise count total rows in a separate fast query
            return self.object_list.model.objects.count()
    
        # Alternative approach for PostgreSQL: fallback count takes > 200ms
        # from django.db import connection, transaction, OperationalError
        # with transaction.atomic(), connection.cursor() as cursor:
        #     cursor.execute('SET LOCAL statement_timeout TO 200;')
        #     try:
        #         return super().count
        #     except OperationalError:
        #         return 9999999999999
