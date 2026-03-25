from __future__ import annotations

from asgiref.sync import sync_to_async
from django.utils import timezone

from abx_dl.events import SnapshotCompletedEvent, SnapshotEvent
from abx_dl.limits import CrawlLimitState
from abx_dl.services.base import BaseService


class SnapshotService(BaseService):
    LISTENS_TO = [SnapshotEvent, SnapshotCompletedEvent]
    EMITS = []

    def __init__(self, bus, *, crawl_id: str, schedule_snapshot):
        self.crawl_id = crawl_id
        self.schedule_snapshot = schedule_snapshot
        super().__init__(bus)
        self.bus.on(SnapshotEvent, self.on_SnapshotEvent)
        self.bus.on(SnapshotCompletedEvent, self.on_SnapshotCompletedEvent)

    async def on_SnapshotEvent(self, event: SnapshotEvent) -> None:
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl

        crawl = await Crawl.objects.aget(id=self.crawl_id)
        snapshot_id: str | None = None
        snapshot = await Snapshot.objects.filter(id=event.snapshot_id, crawl=crawl).afirst()

        if snapshot is not None:
            snapshot.status = Snapshot.StatusChoices.STARTED
            snapshot.retry_at = None
            await snapshot.asave(update_fields=["status", "retry_at", "modified_at"])
            snapshot_id = str(snapshot.id)
        elif event.depth > 0:
            if event.depth <= crawl.max_depth and self._crawl_limit_stop_reason(crawl) != "max_size":
                parent_event = await self.bus.find(
                    SnapshotEvent,
                    past=True,
                    future=False,
                    where=lambda candidate: candidate.depth == event.depth - 1 and self.bus.event_is_child_of(event, candidate),
                )
                parent_snapshot = None
                if parent_event is not None:
                    parent_snapshot = await Snapshot.objects.filter(id=parent_event.snapshot_id, crawl=crawl).afirst()
                if parent_snapshot is not None and self._url_passes_filters(crawl, parent_snapshot, event.url):
                    snapshot = await sync_to_async(Snapshot.from_json, thread_sensitive=True)(
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
                    if snapshot is not None and snapshot.status != Snapshot.StatusChoices.SEALED:
                        snapshot.retry_at = None
                        snapshot.status = Snapshot.StatusChoices.QUEUED
                        await snapshot.asave(update_fields=["status", "retry_at", "modified_at"])
                        snapshot_id = str(snapshot.id)

        if snapshot_id:
            snapshot = await Snapshot.objects.filter(id=snapshot_id).select_related("crawl", "crawl__created_by").afirst()
            if snapshot is not None:
                await sync_to_async(snapshot.ensure_crawl_symlink, thread_sensitive=True)()
        if snapshot_id and event.depth > 0:
            await self.schedule_snapshot(snapshot_id)

    async def on_SnapshotCompletedEvent(self, event: SnapshotCompletedEvent) -> None:
        from archivebox.core.models import Snapshot

        snapshot = await Snapshot.objects.select_related("crawl").filter(id=event.snapshot_id).afirst()
        snapshot_id: str | None = None
        if snapshot is not None:
            snapshot.status = Snapshot.StatusChoices.SEALED
            snapshot.retry_at = None
            snapshot.downloaded_at = snapshot.downloaded_at or timezone.now()
            await snapshot.asave(update_fields=["status", "retry_at", "downloaded_at", "modified_at"])
            if snapshot.crawl_id and self._crawl_limit_stop_reason(snapshot.crawl) == "max_size":
                await (
                    Snapshot.objects.filter(
                        crawl_id=snapshot.crawl_id,
                        status=Snapshot.StatusChoices.QUEUED,
                    )
                    .exclude(id=snapshot.id)
                    .aupdate(
                        status=Snapshot.StatusChoices.SEALED,
                        retry_at=None,
                        modified_at=timezone.now(),
                    )
                )
            snapshot_id = str(snapshot.id)
        if snapshot_id:
            snapshot = await Snapshot.objects.filter(id=snapshot_id).select_related("crawl", "crawl__created_by").afirst()
            if snapshot is not None:
                await sync_to_async(snapshot.write_index_jsonl, thread_sensitive=True)()
                await sync_to_async(snapshot.write_json_details, thread_sensitive=True)()
                await sync_to_async(snapshot.write_html_details, thread_sensitive=True)()

    def _url_passes_filters(self, crawl, parent_snapshot, url: str) -> bool:
        return crawl.url_passes_filters(url, snapshot=parent_snapshot)

    def _crawl_limit_stop_reason(self, crawl) -> str:
        config = dict(crawl.config or {})
        config["CRAWL_DIR"] = str(crawl.output_dir)
        return CrawlLimitState.from_config(config).get_stop_reason()
