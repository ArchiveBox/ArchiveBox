__package__ = "archivebox.misc"

from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.utils.functional import cached_property


class AcceleratedPaginator(Paginator):
    """Paginator that accepts exact count hints for already-optimized query paths."""

    @cached_property
    def count(self):
        if not isinstance(self.object_list, QuerySet):
            return super().count

        query = self.object_list.query
        count_hint = self.object_list.__dict__.get("_archivebox_count_hint")
        if count_hint is None:
            count_hint = query.__dict__.get("_archivebox_count_hint")
        if count_hint is not None:
            if callable(count_hint):
                return count_hint()
            return count_hint

        return super().count
