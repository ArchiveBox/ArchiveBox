__package__ = "archivebox.progressmonitor"

from typing import Literal

from django.conf import settings
from django.db import DatabaseError
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from archivebox.core.permissions import can_view_snapshot, is_admin_user


def progress_endpoint(scope: Literal["crawl", "snapshot"] | None = None, object_id: object | None = None) -> str:
    """Return the canonical same-origin progress endpoint for monitor embeds."""
    if not scope or object_id is None:
        return "/progress.json"
    return f"/progress.json?{scope}_id={str(object_id).replace('-', '')}"


def live_progress_view(request):
    """Simple JSON endpoint for live progress status - used by admin progress monitor."""
    try:
        from archivebox.core.models import Snapshot

        snapshot_id_filter = (request.GET.get("snapshot_id") or "").strip().replace("-", "")
        crawl_id_filter = (request.GET.get("crawl_id") or "").strip().replace("-", "")
        is_admin = is_admin_user(request)

        scoped_snapshot = None
        if snapshot_id_filter:
            import uuid as _uuid

            try:
                _uuid.UUID(snapshot_id_filter)
            except (TypeError, ValueError):
                return JsonResponse({"error": "Invalid snapshot_id"}, status=400)
            scoped_snapshot = Snapshot.objects.filter(id=snapshot_id_filter).select_related("crawl").first()
            if scoped_snapshot is None or not can_view_snapshot(request, scoped_snapshot):
                return JsonResponse({"error": "Permission denied"}, status=403)
        elif not is_admin:
            # Crawl and global scopes require staff: a crawl can mix snapshot ACLs.
            return JsonResponse({"error": "Permission denied"}, status=403)

        from .report import ProgressReport

        payload = ProgressReport(
            request,
            scoped_snapshot=scoped_snapshot,
            crawl_id_filter=crawl_id_filter,
            is_admin=is_admin,
        ).payload()
        if is_admin and not snapshot_id_filter and not crawl_id_filter and request.GET.get("collection") == "1":
            from archivebox.progressmonitor.collection import collection_summary

            payload["collection"] = collection_summary(request.user)
        try:
            import ujson

            return HttpResponse(ujson.dumps(payload), content_type="application/json")
        except ImportError:
            return JsonResponse(payload)
    except (DatabaseError, OSError, RuntimeError, TypeError, ValueError) as e:
        error_payload = {
            "error": str(e),
            "orchestrator_running": False,
            "total_workers": 0,
            "crawls_active": 0,
            "crawls_queued": 0,
            "crawls_recent": 0,
            "snapshots_active": 0,
            "snapshots_queued": 0,
            "archiveresults_active": 0,
            "archiveresults_queued": 0,
            "downloads_active": 0,
            "downloads_queued": 0,
            "indexing_active": 0,
            "indexing_queued": 0,
            "active_crawls": [],
            "server_time": timezone.now().isoformat(),
        }
        if settings.DEBUG:
            import traceback

            error_payload["traceback"] = traceback.format_exc()
        return JsonResponse(error_payload, status=500)
