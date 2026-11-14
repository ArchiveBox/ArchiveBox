__package__ = "archivebox.misc"

from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, QuerySet
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


def snapshot_page(queryset, *, base_queryset, start, size):
    """Read a page plus lookahead, probing the existing order index first.

    Folder/status indexes can make SQLite sort a million matching rows before
    LIMIT. A bounded prefix of the order index avoids that for dense results;
    sparse queries fall back to their own indexes. The original queryset remains
    untouched for exports and select-across actions.
    """
    ordering = queryset.query.order_by or queryset.model._meta.ordering
    fields = {field.name for field in queryset.model._meta.concrete_fields} | {"pk"}
    if queryset.query.where and start + size < 1000 and all(isinstance(field, str) and field.lstrip("-") in fields for field in ordering):
        candidates = list(queryset.model.objects.order_by(*ordering).values_list("pk", flat=True)[: (start + size) * 8])
        page = list(
            base_queryset.filter(pk__in=candidates)
            .filter(Exists(queryset.filter(pk=OuterRef("pk"))))
            .order_by(*ordering)[start : start + size],
        )
        if len(page) == size:
            return page
    return list(queryset[start : start + size])
