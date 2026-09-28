"""Non-blocking, database-only collection totals for the progress monitor."""

import logging
from threading import Lock, Thread
from time import time

from django.core.cache import cache
from django.db import close_old_connections, connections
from django.db.models import Count, Sum


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
                snapshots = snapshots.order_by("modified_at").values_list("modified_at", "downloaded_at", "output_size")
                totals = {"snapshots": 0, "cancelled": 0, "bytes": 0}
                modified_at, offset = None, 0
                while True:
                    batch_scope = snapshots.filter(modified_at__gte=modified_at) if modified_at is not None else snapshots
                    # Use (crawl, status, modified_at), releasing the SQLite read
                    # cursor after each small batch. Never hold a cursor over the
                    # whole crawl, even in this background worker.
                    batch = list(batch_scope[offset : offset + 100])
                    for _, downloaded_at, size in batch:
                        totals["snapshots"] += 1
                        totals["cancelled"] += downloaded_at is None
                        totals["bytes"] += size or 0
                    if len(batch) < 100:
                        break
                    last_modified_at = batch[-1][0]
                    # Only offset within ties; otherwise advance the indexed
                    # timestamp range instead of rescanning previous pages.
                    offset = (offset if last_modified_at == modified_at else 0) + sum(row[0] == last_modified_at for row in batch)
                    modified_at = last_modified_at
                totals["sampled_at"] = time()
                cache.set(key, totals, timeout=3600)
            except Exception:
                logging.getLogger(__name__).exception("Could not refresh crawl totals")
            finally:
                connections.close_all()
                _refresh_lock.release()

        try:
            Thread(target=refresh, name="crawl-summary", daemon=True).start()
        except RuntimeError:
            _refresh_lock.release()
            logging.getLogger(__name__).exception("Could not start crawl totals refresh")
    return summary


def collection_summary(user, *, public=False):
    user_id = None if user.is_superuser else user.pk
    key = "progress-collection:public" if public else f"progress-collection:{'all' if user_id is None else user_id}"
    summary = cache.get(key)
    # Even an indexed SUM scans the index. Never make an HTTP request wait for
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
                cache.set(key, totals, timeout=3600)
            except Exception:
                logging.getLogger(__name__).exception("Could not refresh collection totals")
            finally:
                connections.close_all()
                _refresh_lock.release()

        try:
            Thread(target=refresh, name="collection-summary", daemon=True).start()
        except RuntimeError:
            _refresh_lock.release()
            logging.getLogger(__name__).exception("Could not start collection totals refresh")
    return summary
