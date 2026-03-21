from __future__ import annotations

import re

from asgiref.sync import sync_to_async
from django.utils import timezone

from abx_dl.events import SnapshotCompletedEvent, SnapshotEvent
from abx_dl.services.base import BaseService


class SnapshotService(BaseService):
    LISTENS_TO = [SnapshotEvent, SnapshotCompletedEvent]
    EMITS = []

    def __init__(self, bus, *, crawl_id: str, schedule_snapshot):
        self.crawl_id = crawl_id
        self.schedule_snapshot = schedule_snapshot
        super().__init__(bus)

    async def on_SnapshotEvent(self, event: SnapshotEvent) -> None:
        snapshot_id = await sync_to_async(self._project_snapshot, thread_sensitive=True)(event)
        if snapshot_id and event.depth > 0:
            await self.schedule_snapshot(snapshot_id)

    async def on_SnapshotCompletedEvent(self, event: SnapshotCompletedEvent) -> None:
        await sync_to_async(self._seal_snapshot, thread_sensitive=True)(event.snapshot_id)

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
            snapshot.ensure_crawl_symlink()
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
        snapshot.ensure_crawl_symlink()
        return str(snapshot.id)

    def _url_passes_filters(self, crawl, parent_snapshot, url: str) -> bool:
        from archivebox.config.configset import get_config

        config = get_config(
            user=getattr(crawl, "created_by", None),
            crawl=crawl,
            snapshot=parent_snapshot,
        )

        def to_pattern_list(value):
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                return [pattern.strip() for pattern in value.split(",") if pattern.strip()]
            return []

        allowlist = to_pattern_list(config.get("URL_ALLOWLIST", ""))
        denylist = to_pattern_list(config.get("URL_DENYLIST", ""))

        for pattern in denylist:
            try:
                if re.search(pattern, url):
                    return False
            except re.error:
                continue

        if allowlist:
            for pattern in allowlist:
                try:
                    if re.search(pattern, url):
                        return True
                except re.error:
                    continue
            return False

        return True

    def _seal_snapshot(self, snapshot_id: str) -> None:
        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.filter(id=snapshot_id).first()
        if snapshot is None:
            return
        snapshot.status = Snapshot.StatusChoices.SEALED
        snapshot.retry_at = None
        snapshot.downloaded_at = snapshot.downloaded_at or timezone.now()
        snapshot.save(update_fields=["status", "retry_at", "downloaded_at", "modified_at"])
        snapshot.write_index_jsonl()
        snapshot.write_json_details()
        snapshot.write_html_details()
