from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from asgiref.sync import sync_to_async
from django.utils import timezone
from abx_dl.events import SnapshotCleanupEvent, SnapshotCompletedEvent, SnapshotEvent
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


def prepare_completed_snapshot(
    snapshot_id: str,
    *,
    owned_retry_at,
    was_sealed: bool,
    error: str = "",
):
    from archivebox.core.models import Snapshot

    snapshot = Snapshot.objects.select_related("crawl", "crawl__created_by").filter(id=snapshot_id).first()
    if snapshot is None or snapshot.retry_at != owned_retry_at:
        return None

    _project_snapshot_error(snapshot, error)

    if snapshot.downloaded_at is None:
        snapshot.downloaded_at = timezone.now()
        snapshot.save(update_fields=["downloaded_at", "modified_at"])

    stop_reason = _crawl_limit_stop_reason(snapshot.crawl)
    if snapshot.crawl_id and stop_reason in ("crawl_max_size", "crawl_timeout"):
        Snapshot.objects.filter(
            crawl_id=snapshot.crawl_id,
            status=Snapshot.StatusChoices.QUEUED,
        ).exclude(id=snapshot.id).update(
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
            modified_at=timezone.now(),
        )

    # Materialize the intended final record while holding only the in-process
    # ownership lock. Archive IO happens after releasing it, so even a slow
    # mount cannot prevent the scheduler from renewing this attempt's lease.
    should_seal = not was_sealed and snapshot.status == Snapshot.StatusChoices.STARTED and snapshot.retry_at == owned_retry_at
    return snapshot, should_seal


def _project_snapshot_error(snapshot, error: str) -> None:
    if not error:
        return
    from archivebox.core.models import ArchiveResult
    from django.db.models import Case, F, TextField, Value, When
    from django.db.models.functions import Concat

    # This is projection of the owner's terminal failure, not a scan that
    # guesses completion from rows. Preserve final results/partial output and
    # only end real attempts whose last projected state was still STARTED.
    snapshot.archiveresult_set.filter(status=ArchiveResult.StatusChoices.STARTED).update(
        status=ArchiveResult.StatusChoices.FAILED,
        end_ts=timezone.now(),
        notes=Case(
            When(notes="", then=Value(error)),
            When(notes=error, then=F("notes")),
            default=Concat(F("notes"), Value("\n"), Value(error)),
            output_field=TextField(),
        ),
        modified_at=timezone.now(),
    )
    if error not in snapshot.notes:
        snapshot.notes = f"{snapshot.notes}\n{error}".strip()
        snapshot.save(update_fields=["notes", "modified_at"])


def finalize_completed_snapshot(
    snapshot_id: str,
    *,
    owned_retry_at,
    was_sealed: bool,
    consumed_retry_plugins: list[str] | None = None,
    published_modified_at: datetime | None = None,
    error: str = "",
) -> None:
    from archivebox.core.models import Snapshot
    from django.db.models.functions import Greatest

    snapshot = Snapshot.objects.select_related("crawl", "crawl__created_by").filter(id=snapshot_id).first()
    if snapshot is None or snapshot.retry_at != owned_retry_at:
        return
    # Completion means the attempt ended, including a handled failure. It is
    # never a claim that every extractor succeeded. No filesystem work belongs
    # after this boundary, and no shutdown/finally repair is needed to finish it.
    new_error = bool(error and error not in snapshot.notes)
    _project_snapshot_error(snapshot, error)
    # The canonical record was published before this terminal DB transition.
    # Reuse its date so a copied capture round-trips exactly; a new terminal
    # error instead changes the metadata and must receive its own timestamp.
    completed_modified_at = None if new_error else published_modified_at
    # A user may edit metadata while publication is in flight. Never move that
    # newer DB revision backward to the older published record.
    completion_date = Greatest("modified_at", completed_modified_at or timezone.now())
    consumed_plugins = sorted({str(name).strip() for name in (consumed_retry_plugins or []) if str(name).strip()})
    if consumed_plugins:
        # Consume explicit maintenance only at completion. Clearing this before
        # the canonical write would lose the request if the process died during
        # that write: the next owner would see a sealed row with nothing to run.
        for _attempt in range(3):
            current = Snapshot.objects.only("status", "retry_at", "config").get(pk=snapshot.pk)
            pending_plugins = sorted({str(name).strip() for name in (current.config or {}).get("RETRY_PLUGINS", []) if str(name).strip()})
            if pending_plugins != consumed_plugins or current.status != snapshot.status or current.retry_at != owned_retry_at:
                # A request may add plugins without changing its scheduled
                # time. Only consuming the exact request permits releasing
                # its lease; otherwise the additional work becomes invisible.
                return
            updated = Snapshot.objects.filter(pk=current.pk, status=current.status, config=current.config, retry_at=owned_retry_at).update(
                config={key: value for key, value in current.config.items() if key != "RETRY_PLUGINS"},
                modified_at=completion_date,
            )
            if updated:
                snapshot.refresh_from_db()
                break
        else:
            return
    if not was_sealed and snapshot.status == Snapshot.StatusChoices.STARTED:
        snapshot.seal(modified_at=completed_modified_at)
    elif was_sealed and snapshot.status == Snapshot.StatusChoices.SEALED:
        # Explicit maintenance of a sealed snapshot still owns a lease until
        # completion; releasing it earlier would discard a late storage error.
        Snapshot.objects.filter(
            pk=snapshot.pk,
            retry_at=owned_retry_at,
            config__RETRY_PLUGINS__0__isnull=True,
        ).update(retry_at=None, modified_at=completion_date)


def _crawl_limit_stop_reason(crawl) -> str:
    from archivebox.config.common import get_config

    return crawl.limit_stop_reason(config=get_config(crawl=crawl))


class SnapshotService(BaseService):
    LISTENS_TO = [SnapshotEvent, SnapshotCompletedEvent]
    EMITS = []

    def __init__(self, bus, *, crawl_id: str, interrupted: Callable[[], bool] | None = None):
        self.crawl_id = crawl_id
        self.interrupted = interrupted
        self._run_ownership: dict[str, tuple[str, object, bool, list[str], datetime | None]] = {}
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
            retry_plugins = [str(name).strip() for name in (snapshot.config or {}).get("RETRY_PLUGINS", []) if str(name).strip()]
            async with self._ownership_lock:
                self._run_ownership[str(event.snapshot_id)] = (str(event.event_id), snapshot.retry_at, was_sealed, retry_plugins, None)

    async def on_SnapshotCleanupEvent(self, event: SnapshotCleanupEvent) -> None:
        if not event.finalize_snapshot or (self.interrupted is not None and self.interrupted()):
            return
        async with self._ownership_lock:
            ownership = self._run_ownership.get(str(event.snapshot_id))
        if ownership is None or ownership[0] != str(event.event_parent_id):
            return
        # Discovery/filesystem projection is inside the cleanup phase so any
        # failure reaches its abx-dl owner before the terminal fact is emitted.
        await aproject_discovered_snapshots(event.snapshot_id)

        async with self._ownership_lock:
            # Renewal may have changed the lease while discovery read remote
            # files. Re-read our own current ownership under its existing lock;
            # a stale event may not fail a new owner's ArchiveResult rows.
            ownership = self._run_ownership.get(str(event.snapshot_id))
            if ownership is None or ownership[0] != str(event.event_parent_id) or (self.interrupted is not None and self.interrupted()):
                return
            _, owned_retry_at, was_sealed, retry_plugins, published_modified_at = ownership
            prepared = await sync_to_async(prepare_completed_snapshot, thread_sensitive=True)(
                event.snapshot_id,
                owned_retry_at=owned_retry_at,
                was_sealed=was_sealed,
                error=event.error,
            )
        if prepared is None:
            return

        def publish():
            from django.db import close_old_connections

            try:
                # Registered after abx-dl's cleanup consumer: producers have
                # stopped. Publish before the DB seal. A power loss here leaves
                # the entire attempt restartable; a handled IO failure reaches
                # the owner's terminal error through this cleanup consumer.
                snapshot, should_seal = prepared
                snapshot.finalize_output_metadata()
                snapshot.refresh_from_db()
                record = snapshot.to_json()
                if should_seal:
                    record["status"] = snapshot.StatusChoices.SEALED
                if sorted((snapshot.config or {}).get("RETRY_PLUGINS", [])) == sorted(retry_plugins):
                    record["config"].pop("RETRY_PLUGINS", None)
                snapshot.write_index_jsonl(snapshot_record=record)
                return snapshot.modified_at
            finally:
                close_old_connections()

        published_modified_at = await asyncio.to_thread(publish)
        async with self._ownership_lock:
            ownership = self._run_ownership.get(str(event.snapshot_id))
            if ownership is not None and ownership[0] == str(event.event_parent_id):
                # Keep the receipt with this attempt, not on disk or in a new
                # lifecycle state. Renewal may have advanced the DB lease while
                # publication waited on storage; it must not change this date.
                self._run_ownership[str(event.snapshot_id)] = (*ownership[:4], published_modified_at)

    async def renew_lease(self, snapshot_id: str, lease_until) -> bool | None:
        from archivebox.core.models import Snapshot

        async with self._ownership_lock:
            ownership = self._run_ownership.get(str(snapshot_id))
            if ownership is None or ownership[2]:
                return None
            event_id, owned_retry_at, was_sealed, retry_plugins, published_modified_at = ownership
            updated = await Snapshot.objects.filter(
                id=snapshot_id,
                status=Snapshot.StatusChoices.STARTED,
                retry_at=owned_retry_at,
            ).aupdate(retry_at=lease_until)
            # A lease heartbeat is execution bookkeeping, not changed capture
            # metadata. Advancing modified_at here would invalidate a canonical
            # record while its remote filesystem write was still in flight.
            if updated:
                self._run_ownership[str(snapshot_id)] = (event_id, lease_until, was_sealed, retry_plugins, published_modified_at)
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
        # Leave its durable lease so the next elected runner restarts the entire
        # attempt; there is no persisted hook-level resume state.
        if self.interrupted is not None and self.interrupted():
            return
        _, owned_retry_at, was_sealed, retry_plugins, published_modified_at = ownership
        await sync_to_async(finalize_completed_snapshot, thread_sensitive=True)(
            event.snapshot_id,
            owned_retry_at=owned_retry_at,
            was_sealed=was_sealed,
            consumed_retry_plugins=retry_plugins,
            published_modified_at=published_modified_at,
            error=event.error,
        )
