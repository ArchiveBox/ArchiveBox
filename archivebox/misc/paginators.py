__package__ = "archivebox.misc"

from django.core.paginator import Paginator
from django.utils.functional import cached_property


class AcceleratedPaginator(Paginator):
    """
    Accelerated paginator ignores DISTINCT when counting total number of rows.
    Speeds up SELECT Count(*) on Admin views by >20x.
    https://hakibenita.com/optimizing-the-django-admin-paginator
    """

    @cached_property
    def count(self):
        has_filters = getattr(self.object_list, "_has_filters", None)
        if callable(has_filters) and has_filters():
            # fallback to normal count method on filtered queryset
            return super().count

        model = getattr(self.object_list, "model", None)
        if model is None:
            return super().count

        # otherwise count total rows in a separate fast query
        return model.objects.count()

        # Alternative approach for PostgreSQL: fallback count takes > 200ms
        # from django.db import connection, transaction, OperationalError
        # with transaction.atomic(), connection.cursor() as cursor:
        #     cursor.execute('SET LOCAL statement_timeout TO 200;')
        #     try:
        #         return super().count
        #     except OperationalError:
        #         return 9999999999999
