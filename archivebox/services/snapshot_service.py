from __future__ import annotations

import sys

from asgiref.sync import sync_to_async
from django.utils import timezone
from django.core.exceptions import ValidationError
from rich import print as rprint
from statemachine.exceptions import TransitionNotAllowed
from abx_dl.events import SnapshotCompletedEvent, SnapshotEvent
from abx_dl.limits import CrawlLimitState
from abx_dl.services.base import BaseService


def seal_snapshot_if_finished(snapshot, *, require_finished: bool = True) -> None:
    from archivebox.core.models import Snapshot

    if snapshot.status == Snapshot.StatusChoices.SEALED:
        return
    if snapshot.status == Snapshot.StatusChoices.QUEUED:
        snapshot.sm.tick()
        snapshot.refresh_from_db()
    if snapshot.status == Snapshot.StatusChoices.STARTED and (not require_finished or snapshot.is_finished_processing()):
        try:
            snapshot.sm.seal()
        except TransitionNotAllowed:
            Snapshot.objects.filter(
                pk=snapshot.pk,
                status=Snapshot.StatusChoices.STARTED,
            ).update(
                status=Snapshot.StatusChoices.SEALED,
                retry_at=None,
                modified_at=timezone.now(),
            )
            snapshot.refresh_from_db()
            snapshot.cleanup()
        else:
            snapshot.refresh_from_db()


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

    seal_snapshot_if_finished(snapshot)

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

    def __init__(self, bus, *, crawl_id: str, schedule_snapshot):
        self.crawl_id = crawl_id
        self.schedule_snapshot = schedule_snapshot
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
