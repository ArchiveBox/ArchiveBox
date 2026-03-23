from __future__ import annotations

from asgiref.sync import sync_to_async
from django.utils import timezone

from abx_dl.events import SnapshotCompletedEvent, SnapshotEvent
from abx_dl.services.base import BaseService

from .db import run_db_op


class SnapshotService(BaseService):
    LISTENS_TO = [SnapshotEvent, SnapshotCompletedEvent]
    EMITS = []

    def __init__(self, bus, *, crawl_id: str, schedule_snapshot):
        self.crawl_id = crawl_id
        self.schedule_snapshot = schedule_snapshot
        super().__init__(bus)

    async def on_SnapshotEvent__Outer(self, event: SnapshotEvent) -> None:
        snapshot_id = await run_db_op(self._project_snapshot, event)
        if snapshot_id:
            await sync_to_async(self._ensure_crawl_symlink)(snapshot_id)
        if snapshot_id and event.depth > 0:
            await self.schedule_snapshot(snapshot_id)

    async def on_SnapshotCompletedEvent__Outer(self, event: SnapshotCompletedEvent) -> None:
        snapshot_id = await run_db_op(self._seal_snapshot, event.snapshot_id)
        if snapshot_id:
            await sync_to_async(self._write_snapshot_details)(snapshot_id)

    def _project_snapshot(self, event: SnapshotEvent) -> str | None:
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.get(id=self.crawl_id)

        if event.depth == 0:
            snapshot = Snapshot.objects.filter(id=event.snapshot_id, crawl=crawl).first()
            if snapshot is None:
                return None
            snapshot.status = Snapshot.StatusChoices.STARTED
            snapshot.retry_at = None
            snapshot.save(update_fields=["status", "retry_at", "modified_at"])
            return str(snapshot.id)

        if event.depth > crawl.max_depth:
            return None

        parent_snapshot = Snapshot.objects.filter(id=event.parent_snapshot_id, crawl=crawl).first()
        if parent_snapshot is None:
            return None
        if not self._url_passes_filters(crawl, parent_snapshot, event.url):
            return None

        snapshot = Snapshot.from_json(
            {
                "url": event.url,
                "depth": event.depth,
                "parent_snapshot_id": str(parent_snapshot.id),
                "crawl_id": str(crawl.id),
            },
            overrides={
                "crawl": crawl,
                "snapshot": parent_snapshot,
                "created_by_id": crawl.created_by_id,
            },
            queue_for_extraction=False,
        )
        if snapshot is None:
            return None
        if snapshot.status == Snapshot.StatusChoices.SEALED:
            return None
        snapshot.retry_at = None
        if snapshot.status != Snapshot.StatusChoices.SEALED:
            snapshot.status = Snapshot.StatusChoices.QUEUED
        snapshot.save(update_fields=["status", "retry_at", "modified_at"])
        return str(snapshot.id)

    def _url_passes_filters(self, crawl, parent_snapshot, url: str) -> bool:
        return crawl.url_passes_filters(url, snapshot=parent_snapshot)

    def _seal_snapshot(self, snapshot_id: str) -> str | None:
        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.filter(id=snapshot_id).first()
        if snapshot is None:
            return None
        snapshot.status = Snapshot.StatusChoices.SEALED
        snapshot.retry_at = None
        snapshot.downloaded_at = snapshot.downloaded_at or timezone.now()
        snapshot.save(update_fields=["status", "retry_at", "downloaded_at", "modified_at"])
        return str(snapshot.id)

    def _ensure_crawl_symlink(self, snapshot_id: str) -> None:
        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.filter(id=snapshot_id).select_related("crawl", "crawl__created_by").first()
        if snapshot is not None:
            snapshot.ensure_crawl_symlink()

    def _write_snapshot_details(self, snapshot_id: str) -> None:
        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.filter(id=snapshot_id).select_related("crawl", "crawl__created_by").first()
        if snapshot is None:
            return
        snapshot.write_index_jsonl()
        snapshot.write_json_details()
        snapshot.write_html_details()
