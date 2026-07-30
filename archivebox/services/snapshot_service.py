from __future__ import annotations

import sys
from pathlib import Path

from asgiref.sync import sync_to_async
from django.utils import timezone
from django.core.exceptions import ValidationError
from rich import print as rprint
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
        snapshot.sm.tick()
        snapshot.refresh_from_db()
    if snapshot.status == Snapshot.StatusChoices.STARTED and snapshot.is_finished_processing():
        snapshot.sm.seal()
        snapshot.refresh_from_db()

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
                if not await snapshot.archiveresult_set.aexists():
                    from archivebox.services.runner import snapshot_hooks_for_pending_archiveresults

                    hooks = await sync_to_async(snapshot_hooks_for_pending_archiveresults, thread_sensitive=True)(snapshot)
                    await sync_to_async(snapshot.create_pending_archiveresults, thread_sensitive=True)(hooks=hooks)
                try:
                    await sync_to_async(snapshot.sm.tick, thread_sensitive=True)()
                except ValidationError as err:
                    if "ArchiveBox cannot archive its own admin, web, api, or snapshot URLs." not in str(err):
                        raise
                    await Snapshot.objects.filter(id=snapshot.id).aupdate(
                        status=Snapshot.StatusChoices.SEALED,
                        retry_at=None,
                        modified_at=timezone.now(),
                    )
                    rprint(
                        f"[red][X] Refusing to archive ArchiveBox internal URL for security: {snapshot.url}[/red]",
                        file=sys.stderr,
                    )
                    return
                await sync_to_async(snapshot.refresh_from_db, thread_sensitive=True)()
            elif snapshot.status != Snapshot.StatusChoices.STARTED:
                return
            if snapshot.status != Snapshot.StatusChoices.STARTED:
                return
            await sync_to_async(snapshot.ensure_crawl_symlink, thread_sensitive=True)()

    async def on_SnapshotCompletedEvent(self, event: SnapshotCompletedEvent) -> None:
        await sync_to_async(finalize_completed_snapshot, thread_sensitive=True)(event.snapshot_id)
