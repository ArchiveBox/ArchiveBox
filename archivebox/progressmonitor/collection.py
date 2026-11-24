"""Cached display totals for progress polling and the public snapshot list.

Missing/stale statistics are intentional: returning useful rows and progress
quickly matters more than exact initial counts. Each viewer may poll once per
second; repeating aggregates per request would consume the small server's CPU
and hold SQLite read locks needed by the archiving runner. Callers must accept
None on a cold cache and must never wait for the refresh or count synchronously.

Background reads still take normal SQLite read locks. Existing indexes, short
batches where needed, and throttled refreshes limit their cost; moving work to
a thread does not make a scan free or require switching the database to WAL.
"""

import logging
from contextvars import copy_context
from threading import Lock, Thread
from time import time

from django.core.cache import cache
from django.db import close_old_connections, connections
from django.db.models import Count, Sum


# This is only a process-local gate for background work, not a DB/file lock.
# Every request tries it without waiting; a busy refresh means returning the
# cached value (or None). Serializing refreshes also avoids competing scans for
# different crawls/users when many viewer tabs open at once.
_refresh_lock = Lock()


def crawl_summary(crawl_id, *, snapshot_id=None):
    """Sample sealed snapshot metadata without adding table scans to polls."""
    key = f"progress-crawl:{crawl_id}:{snapshot_id or 'all'}"
    summary = cache.get(key)
    if (summary is None or time() - summary["sampled_at"] >= 30) and _refresh_lock.acquire(blocking=False):
        if not cache.add(f"{key}:refresh", True, timeout=30):
            _refresh_lock.release()
            return summary

        def refresh():
            try:
                close_old_connections()
                from archivebox.core.models import Snapshot

                snapshots = Snapshot.objects.filter(crawl_id=crawl_id, status=Snapshot.StatusChoices.SEALED)
                if snapshot_id is not None:
                    snapshots = snapshots.filter(pk=snapshot_id)
                # Only three totals leave the database. Hydrating each sealed
                # capture and paging through tied timestamps makes this work
                # scale in Python and can revisit rows while captures change.
                totals = snapshots.aggregate(
                    snapshots=Count("*"),
                    cancelled=Count("*") - Count("downloaded_at"),
                    bytes=Sum("output_size", default=0),
                )
                totals["sampled_at"] = time()
                cache.set(key, totals, timeout=3600)
            except Exception:
                logging.getLogger(__name__).exception("Could not refresh crawl totals")
            finally:
                connections.close_all()
                _refresh_lock.release()

        try:
            # The refresh belongs to the request that scheduled it, including
            # its trace and user context, even if the response finishes first.
            Thread(target=copy_context().run, args=(refresh,), name="crawl-summary", daemon=True).start()
        except RuntimeError:
            _refresh_lock.release()
            logging.getLogger(__name__).exception("Could not start crawl totals refresh")
    return summary


def collection_summary(user, *, public=False, refresh=True):
    """Return cached totals immediately and, when due, start one refresh.

    Public pages need no extra AJAX/polling for these totals: an ordinary later
    page load reads the populated cache. Keep this best-effort display cache
    separate from pagination/authorization decisions, which need actual rows.
    """
    user_id = None if user.is_superuser else user.pk
    key = "progress-collection:public" if public else f"progress-collection:{'all' if user_id is None else user_id}"
    summary = cache.get(key)
    # A separate connection cannot count this transaction's uncommitted rows
    # and may block on its writes. Leave the next committed request to refresh.
    if not refresh or connections["default"].in_atomic_block:
        return summary
    # Even indexed COUNT/SUM aggregates scan the index. Never make HTTP wait for
    # that scan on a large collection. Serve stale totals while one worker refreshes;
    # a single non-blocking lock prevents a queue of scans from concurrent clients.
    if (summary is None or time() - summary["sampled_at"] >= 60) and _refresh_lock.acquire(blocking=False):
        # Throttle failures too: a broken/locked database must not trigger work
        # and log output on every sidebar poll. This cache is local to each worker.
        if not cache.add(f"{key}:refresh", True, timeout=60):
            _refresh_lock.release()
            return summary

        def refresh():
            try:
                close_old_connections()
                from archivebox.core.models import Snapshot

                snapshots = Snapshot.objects.all()
                if public:
                    from archivebox.core.permissions import PERMISSIONS_PUBLIC

                    # SQLite can choose a table scan for equality after ANALYZE
                    # on an all-public archive. Equal range bounds keep the count
                    # on the existing permissions index. It is still O(n), so
                    # public pages share this background cache, never await it.
                    # Count the indexed, non-null permissions column so this
                    # needs no Snapshot table reads or new covering-index migration.
                    totals = snapshots.filter(permissions__gte=PERMISSIONS_PUBLIC, permissions__lte=PERMISSIONS_PUBLIC).aggregate(
                        snapshots=Count("permissions"),
                    )
                else:
                    if user_id is not None:
                        snapshots = snapshots.filter(crawl__created_by_id=user_id)
                    # COUNT(*) + SUM(output_size) can use Snapshot's covering size index.
                    # Snapshot.output_size is maintained when ArchiveResult sizes change.
                    totals = snapshots.aggregate(snapshots=Count("*"), bytes=Sum("output_size"))
                totals["bytes"] = totals.get("bytes") or 0
                totals["sampled_at"] = time()
                # Retain old totals longer than the 60s refresh interval so a
                # slow/failed refresh does not force every tab back to a cold
                # count. Staleness is acceptable; blocking page loads is not.
                cache.set(key, totals, timeout=3600)
            except Exception:
                logging.getLogger(__name__).exception("Could not refresh collection totals")
            finally:
                connections.close_all()
                _refresh_lock.release()

        try:
            # Plain threads otherwise drop the initiating request's context.
            Thread(target=copy_context().run, args=(refresh,), name="collection-summary", daemon=True).start()
        except RuntimeError:
            _refresh_lock.release()
            logging.getLogger(__name__).exception("Could not start collection totals refresh")
    return summary


def snapshot_list_count(queryset, *, first_match=False):
    """Debounced display count or public-sidebar witness; never an action scope."""
    from hashlib import sha256
    from django.core.exceptions import EmptyResultSet
    from django.db import connections

    queryset = queryset.order_by().prefetch_related(None).select_related(None)
    try:
        sql, params = queryset.query.sql_with_params()
    except EmptyResultSet:
        return {"count": 0, "snapshot_id": None, "sampled_at": time()}
    key = "snapshot-list-count:" + sha256(repr((queryset.db, sql, params, first_match)).encode()).hexdigest()
    summary = cache.get(key)
    # Uncommitted test/admin transactions must not launch another connection
    # that waits on their writes or counts a different version of those rows.
    if connections[queryset.db].in_atomic_block:
        return summary
    if (summary is None or time() - summary["sampled_at"] >= 60) and _refresh_lock.acquire(blocking=False):
        if not cache.add(f"{key}:refresh", True, timeout=60):
            _refresh_lock.release()
            return summary

        def refresh():
            try:
                close_old_connections()
                # Let the database count/filter its index. Walking every PK in
                # Python made each refresh hydrate the entire collection, even
                # for an empty indexed folder, and contend with HTTP for the GIL.
                # A witness needs at most one row; a count returns only a scalar.
                snapshot_id = next(iter(queryset.values_list("pk", flat=True)[:1]), None) if first_match else None
                count = 0 if first_match else queryset.count()
                snapshot_id = str(snapshot_id) if snapshot_id is not None else None
                cache.set(key, {"count": count, "snapshot_id": snapshot_id, "sampled_at": time()}, timeout=3600)
            except Exception:
                logging.getLogger(__name__).exception("Could not refresh snapshot list count")
            finally:
                connections.close_all()
                _refresh_lock.release()

        try:
            # Attribute this count to its requesting page, not an orphan SQL span.
            Thread(target=copy_context().run, args=(refresh,), name="snapshot-list-count", daemon=True).start()
        except RuntimeError:
            _refresh_lock.release()
            logging.getLogger(__name__).exception("Could not start snapshot list count refresh")
    return summary
