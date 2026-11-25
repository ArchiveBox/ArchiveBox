"""Short-lived, visibility-scoped counts for Library sidebar ordering."""

from heapq import nsmallest
from hashlib import sha256
from types import SimpleNamespace

from django.core.cache import caches
from django.db import connections
from django.db.models import Count, Exists, Max

from archivebox.core.domain_grouping import domain_search_term, group_domain_key
from archivebox.core.tag_util import SnapshotTag, _tag_snapshot_memberships


def _totals(key, using, build):
    connection = connections[using]
    if connection.in_atomic_block:
        return build()
    # Reuse the collection-local scratch cache across web workers, without
    # placing private rankings in the public namespace or retaining them in RAM.
    prefix = sha256(f"{using}:{connection.settings_dict['NAME']}".encode()).hexdigest()[:16]
    scope = ":".join(str(part) for part in key)
    return caches["search_results"].get_or_set(f"library-sidebar:{prefix}:{scope}", build, timeout=30)


def _sort_value(sort, metric):
    if sort == "count":
        return -metric
    # Missing snapshots sort after any real capture.
    return -metric.timestamp() if metric is not None else 1e20


def _rank(entries, order, cursor, limit):
    if cursor is not None:
        boundary = tuple(cursor)
        entries = (entry for entry in entries if order(entry) > boundary)
    rows = nsmallest(limit + 1, entries, key=order)
    # The cursor is based on the sorted grouping identity, not a potentially
    # different representative snapshot.
    return rows[:limit], list(order(rows[limit - 1])) if len(rows) > limit else None


def ranked_tags_page(tags, *, public, sort, cursor, limit):
    def collect():
        memberships = SnapshotTag.objects.using(tags.db).order_by()
        if public:
            memberships = memberships.filter(snapshot__permissions="public")
        aggregates = memberships.values("tag_id").annotate(
            **({"total": Count("*")} if sort == "count" else {"newest": Max("snapshot__created_at")}),
        )
        return {int(row["tag_id"]): (row.get("total", 1), row.get("newest")) for row in aggregates if row["tag_id"] is not None}

    stats = _totals(("tags", public, sort), tags.db, collect)
    if public:
        # Cache age must not make a tag with no remaining public captures visible.
        tags = tags.filter(Exists(_tag_snapshot_memberships().filter(snapshot__permissions="public")))
    entries = ((pk, name, *stats.get(pk, (0, None))) for pk, name in tags.order_by().values_list("pk", "name"))
    rows, next_key = _rank(
        entries,
        lambda row: (_sort_value(sort, row[2] if sort == "count" else row[3]), row[1].casefold(), row[0]),
        cursor,
        limit,
    )
    return [SimpleNamespace(pk=pk, name=name, has_snapshots=bool(total)) for pk, name, total, _ in rows], next_key


def ranked_domains_page(snapshots, term, *, public, sort, cursor, limit):
    def collect():
        groups = {}
        hosts = snapshots.filter(reversed_domain__gt="").order_by().values("reversed_domain")
        if sort != "name":
            alias, annotation = ("metric", Count("*") if sort == "count" else Max("created_at"))
            hosts = hosts.annotate(**{alias: annotation})
        else:
            hosts = hosts.distinct()
        fields = ("reversed_domain",) if sort == "name" else ("reversed_domain", "metric")
        for key, *value in hosts.values_list(*fields).iterator(chunk_size=1000):
            name, scope = group_domain_key(key)
            metric = value[0] if value else 0
            if name in groups:
                _, prev_key, prev_metric = groups[name]
                metric = prev_metric + metric if sort == "count" else max(prev_metric, metric)
                key = min(prev_key, key)
            groups[name] = (scope, key, metric)
        return groups

    groups = _totals(("domains", public, sort), snapshots.db, collect)
    needle = domain_search_term(term)
    entries = ((name, *row) for name, row in groups.items() if needle in name.casefold())
    if sort == "name":
        order = lambda row: (row[0].casefold(), row[1])  # noqa: E731
    else:
        order = lambda row: (_sort_value(sort, row[3]), row[0].casefold(), row[1])  # noqa: E731
    rows, next_key = _rank(entries, order, cursor, limit)
    return {name: (scope, key) for name, scope, key, _ in rows}, next_key
