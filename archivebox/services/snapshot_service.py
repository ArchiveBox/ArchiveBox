from __future__ import annotations

from pathlib import Path

from asgiref.sync import sync_to_async
from django.utils import timezone
from abx_dl.events import SnapshotCompletedEvent, SnapshotEvent
from abx_dl.limits import CrawlLimitState
from abx_dl.services.base import BaseService


def project_discovered_snapshots(snapshot_id: str) -> list:
    """Persist parser output before the parent Snapshot can enter a final state."""
    from archivebox.config.common import get_config
    from archivebox.core.models import Snapshot
    from archivebox.plugins.hooks import collect_urls_from_plugins

    snapshot = Snapshot.objects.select_related("crawl", "crawl__created_by", "crawl__persona").filter(id=snapshot_id).first()
    if snapshot is None:
        return []
    crawl = snapshot.crawl
    if crawl.status not in crawl.RUNNABLE_STATES or crawl.is_paused or snapshot.depth >= crawl.max_depth:
        return []

    discovered_urls = collect_urls_from_plugins(Path(snapshot.output_dir))
    if not discovered_urls:
        return []

    config = get_config(crawl=crawl, snapshot=snapshot).for_crawl_runtime(
        crawl=crawl,
        snapshot=snapshot,
        persona=crawl.resolve_persona(),
        crawl_output_dir=crawl.output_dir,
        snapshot_output_dir=snapshot.output_dir,
    )
    if CrawlLimitState.from_config(config).get_stop_reason() in ("crawl_max_size", "crawl_timeout"):
        return []
    return crawl.create_discovered_snapshots(snapshot, discovered_urls, depth=snapshot.depth + 1)


def finalize_completed_snapshot(
    snapshot_id: str,
    *,
    output_dir=None,
    crawl_limit_stop_reason: str | None = None,
) -> None:
    from archivebox.core.models import Snapshot

    snapshot = Snapshot.objects.select_related("crawl", "crawl__created_by").filter(id=snapshot_id).first()
    if snapshot is None:
        return

    # urls.jsonl is durable hook output. Project it while the Snapshot/Crawl are
    # still runnable so an interruption cannot seal a parser root after its
    # ArchiveResults finish but before its discovered child rows are persisted.
    project_discovered_snapshots(str(snapshot.id))

    if snapshot.downloaded_at is None:
        snapshot.downloaded_at = timezone.now()
        snapshot.save(update_fields=["downloaded_at", "modified_at"])

    stop_reason = crawl_limit_stop_reason if crawl_limit_stop_reason is not None else _crawl_limit_stop_reason(snapshot.crawl)
    if snapshot.crawl_id and stop_reason in ("crawl_max_size", "crawl_timeout"):
        Snapshot.objects.filter(
            crawl_id=snapshot.crawl_id,
            status=Snapshot.StatusChoices.QUEUED,
        ).exclude(id=snapshot.id).update(
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
            modified_at=timezone.now(),
        )

    if snapshot.status == Snapshot.StatusChoices.QUEUED:
        snapshot.advance_lifecycle()
        snapshot.refresh_from_db()
    # SnapshotCompletedEvent is abx-dl's authoritative signal that the complete
    # snapshot hook sequence (including cleanup) finished. ArchiveResult rows
    # are projections of that work, never prerequisites used to decide whether
    # the Snapshot may seal.
    if snapshot.status == Snapshot.StatusChoices.STARTED:
        snapshot.seal()
        snapshot.refresh_from_db()

    if "RETRY_PLUGINS" in (snapshot.config or {}):
        snapshot.config = {key: value for key, value in snapshot.config.items() if key != "RETRY_PLUGINS"}
        snapshot.save(update_fields=["config", "modified_at"])

    snapshot.write_index_jsonl(output_dir=output_dir)


def _crawl_limit_stop_reason(crawl) -> str:
    from archivebox.config.common import get_config

    config_model = get_config(crawl=crawl)
    config = config_model.for_crawl_runtime(
        crawl=crawl,
        persona=crawl.resolve_persona(),
    )
    return CrawlLimitState.from_config(config).get_stop_reason()


class SnapshotService(BaseService):
    LISTENS_TO = [SnapshotEvent, SnapshotCompletedEvent]
    EMITS = []

    def __init__(self, bus, *, crawl_id: str):
        self.crawl_id = crawl_id
        super().__init__(bus)
        self.bus.on(SnapshotEvent, self.on_SnapshotEvent)
        self.bus.on(SnapshotCompletedEvent, self.on_SnapshotCompletedEvent)

    async def on_SnapshotEvent(self, event: SnapshotEvent) -> None:
        from archivebox.core.models import Snapshot

        snapshot = await Snapshot.objects.filter(id=event.snapshot_id, crawl_id=self.crawl_id).afirst()

        if snapshot is not None:
            if snapshot.is_paused:
                return
            if snapshot.status == Snapshot.StatusChoices.QUEUED:
                await sync_to_async(snapshot.advance_lifecycle, thread_sensitive=True)()
                await sync_to_async(snapshot.refresh_from_db, thread_sensitive=True)()
            elif snapshot.status != Snapshot.StatusChoices.STARTED:
                return
            if snapshot.status != Snapshot.StatusChoices.STARTED:
                return
            await sync_to_async(snapshot.ensure_crawl_symlink, thread_sensitive=True)()

    async def on_SnapshotCompletedEvent(self, event: SnapshotCompletedEvent) -> None:
        await sync_to_async(finalize_completed_snapshot, thread_sensitive=True)(event.snapshot_id)
