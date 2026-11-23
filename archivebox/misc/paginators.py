__package__ = "archivebox.misc"

from django.core.paginator import Paginator
from django.db.models import Exists, F, OrderBy, OuterRef, QuerySet
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


def snapshot_page(queryset, *, base_queryset, start, size, count=None):
    return list(iter_snapshot_page(queryset, base_queryset=base_queryset, start=start, size=size, count=count))


def iter_snapshot_page(queryset, *, base_queryset, start, size, count=None, chunk_size=128):
    """Read a page plus lookahead, probing the existing order index first.

    Folder/status indexes can make SQLite sort a million matching rows before
    LIMIT. A bounded prefix of the order index avoids that for dense results;
    sparse queries fall back to their own indexes. The original queryset remains
    untouched for exports and select-across actions.
    """
    # If an indexed exact count is already available, a small filtered scope
    # needs no speculative scan of unrelated rows. This is bounded by the same
    # maximum 1,000 * 8 candidates as the order-index probe below.
    if queryset._result_cache is not None:
        yield from queryset[start : start + size]
        return
    if count is not None and count <= 8000:
        yield from queryset[start : start + size].iterator(chunk_size=chunk_size)
        return
    ordering = queryset.query.order_by or queryset.model._meta.ordering
    fields = {field.name for field in queryset.model._meta.concrete_fields} | {"pk"}
    if (
        queryset.query.where
        and start + size < 1000
        and all(
            (isinstance(field, str) and field.lstrip("-") in fields)
            or (isinstance(field, OrderBy) and isinstance(field.expression, F) and field.expression.name in fields)
            for field in ordering
        )
    ):
        # Keep the bounded IDs inside SQL; hydrating and rebinding thousands of
        # UUIDs cost more than the index probe itself.
        ordered_ids = queryset.model.objects.order_by(*ordering).values_list("pk", flat=True)
        # For a first page, publish the first handful before checking hundreds
        # of expensive predicates (e.g. JSON output paths). Disjoint slices
        # of the same order preserve page order and never repeat a candidate.
        total = start + size
        stops = (min(16, size), size, total * 8) if start == 0 else (total * 8,)
        lower = 0
        for upper in dict.fromkeys(stops):
            probe = (
                base_queryset.filter(pk__in=ordered_ids[lower:upper]).filter(Exists(queryset.filter(pk=OuterRef("pk")))).order_by(*ordering)
            )
            served = 0
            for pk in probe[start : start + size].iterator(chunk_size=chunk_size):
                served += 1
                yield pk
            if served == size:
                return
            size -= served
            lower = upper
        start = total - size
    yield from queryset[start : start + size].iterator(chunk_size=chunk_size)
