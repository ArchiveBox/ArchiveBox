from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from asgiref.sync import sync_to_async
from django.utils import timezone
from abx_dl.events import SnapshotCompletedEvent, SnapshotEvent
from abx_dl.services.base import BaseService


def _load_discovery_context(snapshot_id: str):
    from archivebox.config.common import get_config
    from archivebox.core.models import Snapshot

    snapshot = Snapshot.objects.select_related("crawl", "crawl__created_by", "crawl__persona").filter(id=snapshot_id).first()
    if snapshot is None:
        return None
    crawl = snapshot.crawl
    if crawl.status not in crawl.RUNNABLE_STATES or crawl.is_paused or snapshot.depth >= crawl.max_depth:
        return None
    return snapshot, get_config(crawl=crawl, snapshot=snapshot)


def _read_discovery_outputs(context):
    from archivebox.plugins.hooks import collect_urls_from_plugins

    snapshot, effective_config = context
    crawl = snapshot.crawl
    discovery_plugins = {name.strip() for name in effective_config.CRAWL_DISCOVERY_PLUGINS.split(",") if name.strip()}
    discovered_urls = collect_urls_from_plugins(Path(snapshot.output_dir))
    if discovery_plugins:
        # Provenance comes from the containing plugin directory, independently
        # of fields supplied by archived JSONL records.
        discovered_urls = [record for record in discovered_urls if record["plugin"] in discovery_plugins]
    if not discovered_urls:
        return [], {}
    config = effective_config.for_crawl_runtime(
        crawl=crawl,
        snapshot=snapshot,
        persona=crawl.persona,
        crawl_output_dir=crawl.output_dir,
        snapshot_output_dir=snapshot.output_dir,
    )
    return discovered_urls, config


def _project_discovered_snapshots(context, output) -> list:
    snapshot, _effective_config = context
    discovered_urls, config = output
    if not discovered_urls:
        return []
    crawl = snapshot.crawl
    if crawl.limit_stop_reason(config=config) in ("crawl_max_size", "crawl_timeout"):
        return []
    return crawl.create_discovered_snapshots(snapshot, discovered_urls, depth=snapshot.depth + 1)


def project_discovered_snapshots(snapshot_id: str) -> list:
    """Persist parser output before the parent Snapshot can enter a final state."""
    context = _load_discovery_context(snapshot_id)
    return _project_discovered_snapshots(context, _read_discovery_outputs(context)) if context else []


async def aproject_discovered_snapshots(snapshot_id: str) -> list:
    # Reading all parser files can wait on FUSE. Materialize ORM relations first,
    # then release the shared Django executor until the records are ready to save.
    context = await sync_to_async(_load_discovery_context, thread_sensitive=True)(snapshot_id)
    if context is None:
        return []
    output = await asyncio.to_thread(_read_discovery_outputs, context)
    return await sync_to_async(_project_discovered_snapshots, thread_sensitive=True)(context, output)


def finalize_completed_snapshot(
    snapshot_id: str,
    *,
    owned_retry_at,
    was_sealed: bool,
    consumed_retry_plugins: list[str] | None = None,
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

    # SnapshotCompletedEvent finishes an attempt, including abort cleanup. An
    # explicit user abort deliberately seals that point-in-time capture; the
    # runner's interrupted-owner guard below keeps takeover work resumable.
    # ArchiveResult rows are projections of that work, never prerequisites used
    # to decide whether the Snapshot may seal.
    if not was_sealed and snapshot.status == Snapshot.StatusChoices.STARTED and snapshot.retry_at == owned_retry_at:
        snapshot.seal()
        snapshot.refresh_from_db()

    consumed_plugins = sorted({str(name).strip() for name in (consumed_retry_plugins or []) if str(name).strip()})
    if consumed_plugins and snapshot.status == Snapshot.StatusChoices.SEALED:
        for _attempt in range(3):
            current = Snapshot.objects.only("status", "retry_at", "config").get(pk=snapshot.pk)
            pending_plugins = sorted(
                {str(name).strip() for name in (current.config or {}).get("RETRY_PLUGINS", []) if str(name).strip()},
            )
            if pending_plugins != consumed_plugins:
                break
            owned_filter = {"retry_at": owned_retry_at} if was_sealed else {"retry_at__isnull": True}
            updates: dict[str, object] = {
                "config": {key: value for key, value in current.config.items() if key != "RETRY_PLUGINS"},
                "modified_at": timezone.now(),
            }
            if was_sealed:
                updates["retry_at"] = None
            updated = Snapshot.objects.filter(
                pk=current.pk,
                status=Snapshot.StatusChoices.SEALED,
                config=current.config,
                **owned_filter,
            ).update(**updates)
            if updated:
                snapshot.refresh_from_db()
                break

    snapshot.write_index_jsonl(output_dir=output_dir)


def _crawl_limit_stop_reason(crawl) -> str:
    from archivebox.config.common import get_config

    return crawl.limit_stop_reason(config=get_config(crawl=crawl))


class SnapshotService(BaseService):
    LISTENS_TO = [SnapshotEvent, SnapshotCompletedEvent]
    EMITS = []

    def __init__(self, bus, *, crawl_id: str, interrupted: Callable[[], bool] | None = None):
        self.crawl_id = crawl_id
        self.interrupted = interrupted
        self._run_ownership: dict[str, tuple[str, object, bool, list[str]]] = {}
        self._ownership_lock = asyncio.Lock()
        super().__init__(bus)
        self.bus.on(SnapshotEvent, self.on_SnapshotEvent)
        self.bus.on(SnapshotCompletedEvent, self.on_SnapshotCompletedEvent)

    async def on_SnapshotEvent(self, event: SnapshotEvent) -> None:
        from archivebox.core.models import Snapshot

        snapshot = await Snapshot.objects.filter(id=event.snapshot_id, crawl_id=self.crawl_id).afirst()

        if snapshot is not None:
            if snapshot.is_paused:
                return
            was_sealed = snapshot.status == Snapshot.StatusChoices.SEALED
            if snapshot.status == Snapshot.StatusChoices.QUEUED:
                await sync_to_async(snapshot.advance_lifecycle, thread_sensitive=True)()
                await sync_to_async(snapshot.refresh_from_db, thread_sensitive=True)()
            elif snapshot.status not in (Snapshot.StatusChoices.STARTED, Snapshot.StatusChoices.SEALED):
                return
            if snapshot.status == Snapshot.StatusChoices.STARTED:
                await sync_to_async(snapshot.reconcile_filesystem_links, thread_sensitive=True)()
            retry_plugins = [str(name).strip() for name in (snapshot.config or {}).get("RETRY_PLUGINS", []) if str(name).strip()]
            async with self._ownership_lock:
                self._run_ownership[str(event.snapshot_id)] = (str(event.event_id), snapshot.retry_at, was_sealed, retry_plugins)

    async def renew_lease(self, snapshot_id: str, lease_until) -> bool | None:
        from archivebox.core.models import Snapshot

        async with self._ownership_lock:
            ownership = self._run_ownership.get(str(snapshot_id))
            if ownership is None or ownership[2]:
                return None
            event_id, owned_retry_at, was_sealed, retry_plugins = ownership
            updated = await Snapshot.objects.filter(
                id=snapshot_id,
                status=Snapshot.StatusChoices.STARTED,
                retry_at=owned_retry_at,
            ).aupdate(
                retry_at=lease_until,
                modified_at=timezone.now(),
            )
            if updated:
                self._run_ownership[str(snapshot_id)] = (event_id, lease_until, was_sealed, retry_plugins)
            return bool(updated)

    async def on_SnapshotCompletedEvent(self, event: SnapshotCompletedEvent) -> None:
        snapshot_id = str(event.snapshot_id)
        async with self._ownership_lock:
            ownership = self._run_ownership.get(snapshot_id)
            if ownership is None or ownership[0] != str(event.event_parent_id):
                return
            self._run_ownership.pop(snapshot_id, None)
        # abx-dl also emits completion after abort cleanup, even before the
        # first hook. Explicit user aborts seal a point-in-time capture so later
        # work cannot silently mix observations taken days apart; reopening it
        # is a separate user action. Takeover only replaces its execution owner.
        # Consult the runner's synchronous signal state: an exiting owner cannot
        # rely on another bus event arriving before this completion projector runs.
        # Leave its durable lease for the next elected runner's startup recovery.
        if self.interrupted is not None and self.interrupted():
            return
        _, owned_retry_at, was_sealed, retry_plugins = ownership
        await sync_to_async(finalize_completed_snapshot, thread_sensitive=True)(
            event.snapshot_id,
            owned_retry_at=owned_retry_at,
            was_sealed=was_sealed,
            consumed_retry_plugins=retry_plugins,
        )
