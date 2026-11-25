__package__ = "archivebox.misc"

from django.core.paginator import Paginator
from django.db import connections
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
    fields = {field.name: field for field in queryset.model._meta.concrete_fields}
    fields["pk"] = queryset.model._meta.pk
    # SQLite orders NULLs first in a bare ascending order. Its index still has
    # to sort the whole leading group by the tiebreaker for every bounded slice.
    nulls_first_with_ties = (
        len(ordering) > 1
        and isinstance(ordering[0], str)
        and ordering[0] in fields
        and fields[ordering[0]].null
        and connections[queryset.db].vendor == "sqlite"
    )
    if (
        queryset.query.where
        and start + size < 1000
        and not nulls_first_with_ties
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
        initial_limit = total * 8
        stops = (initial_limit,)
        if not start:
            stops = (min(16, size), size, initial_limit, min(total * 16, 8000), min(total * 24, 8000))
        candidate = queryset.filter(pk=OuterRef("pk"))
        candidate.query._archivebox_candidate_row = True
        lower = 0
        for upper in dict.fromkeys(stops):
            # With enough matches in the initial window, the next few index
            # ranges can fill the page before a filtered sort scans the scope.
            # Keep the normal filtered plan for sparse or empty results.
            if lower == initial_limit and (total - size) * 3 < total:
                break
            probe = base_queryset.filter(pk__in=ordered_ids[lower:upper]).filter(Exists(candidate)).order_by(*ordering)
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
