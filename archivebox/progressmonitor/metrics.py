"""Infrequent, read-only telemetry. Polls return cached data without waiting."""

import json
import logging
from datetime import timedelta
from pathlib import Path
from threading import Lock, Thread
from time import time

from atomicwrites import atomic_write
from django.core.cache import cache
from django.db import close_old_connections, connections
from django.db.models import Count, Q
from django.utils import timezone

from archivebox.config.constants import CONSTANTS
from archivebox.machine.detect import get_live_system_stats

_refresh_lock = Lock()
REFRESH_SECONDS = 60


def system_metrics_path():
    """Local sampler output shared with collection-side tools."""
    from archivebox.config.common import get_config

    return Path(get_config(resolve_plugins=False).TMP_DIR) / "progress-system-metrics.json"


def progress_metrics(user, *, crawl_id=None, snapshot_id=None):
    """Keep authorization scope in the cache key; never disclose host stats to guests."""
    if not (user.is_staff or user.is_superuser):
        return None
    owner_id = None if user.is_superuser else user.pk
    key = f"progress-metrics:{owner_id}:{crawl_id}:{snapshot_id}"
    try:
        summary = cache.get(key)
    except Exception:
        # Optional telemetry must not break capture progress when its cache fails.
        return None
    if (summary is None or time() - summary["sampled_at"] >= REFRESH_SECONDS) and _refresh_lock.acquire(blocking=False):
        try:
            refresh_due = cache.add(f"{key}:refresh", True, timeout=REFRESH_SECONDS)
        except Exception:
            refresh_due = False
        if not refresh_due:
            _refresh_lock.release()
            return summary

        def refresh():
            try:
                close_old_connections()
                from archivebox.core.models import Snapshot

                now = timezone.now()
                # Existing downloaded_at index bounds this to one hour, not the
                # archive's lifetime. Finish SQL before any OS/filesystem work.
                scope = Snapshot.objects.filter(downloaded_at__gte=now - timedelta(hours=1), downloaded_at__lte=now)
                if owner_id is not None:
                    scope = scope.filter(crawl__created_by_id=owner_id)
                if crawl_id:
                    scope = scope.filter(crawl_id=crawl_id)
                if snapshot_id:
                    scope = scope.filter(pk=snapshot_id)
                throughput = scope.aggregate(
                    last_hour=Count("downloaded_at"),
                    last_30_minutes=Count("downloaded_at", filter=Q(downloaded_at__gte=now - timedelta(minutes=30))),
                )
                system = cache.get("progress-system-metrics")
                if system is None or time() - system["sampled_at"] >= REFRESH_SECONDS:
                    system = get_live_system_stats(CONSTANTS.DATA_DIR)
                    cache.set("progress-system-metrics", system, timeout=3600)
                    # Publish once per sample; readers never start another sampler.
                    # Failure of this optional handoff must not hide UI metrics.
                    try:
                        filename = system_metrics_path()
                        filename.parent.mkdir(parents=True, exist_ok=True)
                        with atomic_write(filename, overwrite=True) as stream:
                            json.dump(system, stream)
                    except OSError:
                        logging.getLogger(__name__).warning("Could not publish system metrics", exc_info=True)
                cache.set(
                    key,
                    {"sampled_at": time(), "throughput": throughput, "system": system},
                    timeout=3600,
                )
            except Exception:
                logging.getLogger(__name__).exception("Could not sample progress metrics")
            finally:
                connections.close_all()
                _refresh_lock.release()

        try:
            Thread(target=refresh, name="progress-metrics", daemon=True).start()
        except RuntimeError:
            _refresh_lock.release()
            logging.getLogger(__name__).exception("Could not start progress metrics sampler")
    return summary
