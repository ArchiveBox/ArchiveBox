"""Non-blocking, database-only collection totals for the progress monitor."""

import logging
from threading import Lock, Thread
from time import time

from django.core.cache import cache
from django.db import close_old_connections, connections
from django.db.models import Count, Sum


_refresh_lock = Lock()


def collection_summary(user):
    user_id = None if user.is_superuser else user.pk
    key = f"progress-collection:{'all' if user_id is None else user_id}"
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
                if user_id is not None:
                    snapshots = snapshots.filter(crawl__created_by_id=user_id)
                # COUNT(*) + SUM(output_size) can use Snapshot's covering size index.
                # Snapshot.output_size is maintained when ArchiveResult sizes change.
                totals = snapshots.aggregate(snapshots=Count("*"), bytes=Sum("output_size"))
                totals["bytes"] = totals["bytes"] or 0
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
