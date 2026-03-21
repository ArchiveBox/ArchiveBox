from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from django.utils import timezone

from abx_dl.events import BinaryEvent
from abx_dl.models import INSTALL_URL, Snapshot as AbxSnapshot, discover_plugins
from abx_dl.orchestrator import create_bus, download, install_plugins as abx_install_plugins, setup_services as setup_abx_services

from .archive_result_service import ArchiveResultService
from .binary_service import BinaryService
from .crawl_service import CrawlService
from .machine_service import MachineService
from .process_service import ProcessService
from .snapshot_service import SnapshotService
from .tag_service import TagService


def _bus_name(prefix: str, identifier: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in identifier)
    return f"{prefix}_{normalized}"


def _selected_plugins_from_config(config: dict[str, Any]) -> list[str] | None:
    raw = str(config.get("PLUGINS") or "").strip()
    if not raw:
        return None
    return [name.strip() for name in raw.split(",") if name.strip()]


def _attach_bus_trace(bus) -> None:
    trace_target = (os.environ.get("ARCHIVEBOX_BUS_TRACE") or "").strip()
    if not trace_target:
        return
    if getattr(bus, "_archivebox_trace_task", None) is not None:
        return

    trace_path = None if trace_target in {"1", "-", "stderr"} else Path(trace_target)
    stop_event = asyncio.Event()

    async def trace_loop() -> None:
        seen_event_ids: set[str] = set()
        while not stop_event.is_set():
            for event_id, event in list(bus.event_history.items()):
                if event_id in seen_event_ids:
                    continue
                seen_event_ids.add(event_id)
                payload = event.model_dump(mode="json")
                payload["bus_name"] = bus.name
                line = json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))
                if trace_path is None:
                    print(line, file=sys.stderr, flush=True)
                else:
                    trace_path.parent.mkdir(parents=True, exist_ok=True)
                    with trace_path.open("a", encoding="utf-8") as handle:
                        handle.write(line + "\n")
            await asyncio.sleep(0.05)

    bus._archivebox_trace_stop = stop_event
    bus._archivebox_trace_task = asyncio.create_task(trace_loop())


async def _stop_bus_trace(bus) -> None:
    stop_event = getattr(bus, "_archivebox_trace_stop", None)
    trace_task = getattr(bus, "_archivebox_trace_task", None)
    if stop_event is None or trace_task is None:
        return
    stop_event.set()
    await asyncio.gather(trace_task, return_exceptions=True)
    bus._archivebox_trace_stop = None
    bus._archivebox_trace_task = None


class CrawlRunner:
    MAX_CONCURRENT_SNAPSHOTS = 8

    def __init__(self, crawl, *, snapshot_ids: list[str] | None = None, selected_plugins: list[str] | None = None):
        self.crawl = crawl
        self.bus = create_bus(name=_bus_name("ArchiveBox", str(crawl.id)), total_timeout=3600.0)
        self.plugins = discover_plugins()
        self.process_service = ProcessService(self.bus)
        self.machine_service = MachineService(self.bus)
        self.binary_service = BinaryService(self.bus)
        self.tag_service = TagService(self.bus)
        self.crawl_service = CrawlService(self.bus, crawl_id=str(crawl.id))
        self.snapshot_service = SnapshotService(self.bus, crawl_id=str(crawl.id), schedule_snapshot=self.enqueue_snapshot)
        self.archive_result_service = ArchiveResultService(self.bus, process_service=self.process_service)
        self.selected_plugins = selected_plugins
        self.initial_snapshot_ids = snapshot_ids
        self.snapshot_tasks: dict[str, asyncio.Task[None]] = {}
        self.snapshot_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_SNAPSHOTS)
        self.abx_services = None
        self.persona = None
        self.base_config: dict[str, Any] = {}
        self.primary_url = ""

    async def run(self) -> None:
        from asgiref.sync import sync_to_async
        from archivebox.crawls.models import Crawl

        try:
            await sync_to_async(self._prepare, thread_sensitive=True)()
            _attach_bus_trace(self.bus)
            self.abx_services = setup_abx_services(
                self.bus,
                plugins=self.plugins,
                config_overrides=self.base_config,
                auto_install=True,
                emit_jsonl=False,
            )
            if self.crawl.get_system_task() == INSTALL_URL:
                await self._run_install_crawl()
            else:
                snapshot_ids = await sync_to_async(self._initial_snapshot_ids, thread_sensitive=True)()
                if snapshot_ids:
                    root_snapshot_id = snapshot_ids[0]
                    await self._run_crawl_setup(root_snapshot_id)
                    for snapshot_id in snapshot_ids:
                        await self.enqueue_snapshot(snapshot_id)
                    await self._wait_for_snapshot_tasks()
                    await self._run_crawl_cleanup(root_snapshot_id)
            if self.abx_services is not None:
                await self.abx_services.process.wait_for_background_monitors()
        finally:
            await _stop_bus_trace(self.bus)
            await self.bus.stop()
            await sync_to_async(self._cleanup_persona, thread_sensitive=True)()
            crawl = await sync_to_async(Crawl.objects.get, thread_sensitive=True)(id=self.crawl.id)
            if crawl.status != Crawl.StatusChoices.SEALED:
                crawl.status = Crawl.StatusChoices.SEALED
                crawl.retry_at = None
                await sync_to_async(crawl.save, thread_sensitive=True)(update_fields=["status", "retry_at", "modified_at"])

    async def enqueue_snapshot(self, snapshot_id: str) -> None:
        task = self.snapshot_tasks.get(snapshot_id)
        if task is not None and not task.done():
            return
        task = asyncio.create_task(self._run_snapshot(snapshot_id))
        self.snapshot_tasks[snapshot_id] = task

    async def _wait_for_snapshot_tasks(self) -> None:
        while True:
            active = [task for task in self.snapshot_tasks.values() if not task.done()]
            if not active:
                return
            await asyncio.gather(*active)

    def _prepare(self) -> None:
        from archivebox.config.configset import get_config

        self.primary_url = self.crawl.get_urls_list()[0] if self.crawl.get_urls_list() else ""
        self.persona = self.crawl.resolve_persona()
        self.base_config = get_config(crawl=self.crawl)
        if self.selected_plugins is None:
            self.selected_plugins = _selected_plugins_from_config(self.base_config)
        if self.persona:
            chrome_binary = str(self.base_config.get("CHROME_BINARY") or "")
            self.base_config.update(self.persona.prepare_runtime_for_crawl(self.crawl, chrome_binary=chrome_binary))

    def _cleanup_persona(self) -> None:
        if self.persona:
            self.persona.cleanup_runtime_for_crawl(self.crawl)

    def _create_root_snapshots(self) -> list[str]:
        created = self.crawl.create_snapshots_from_urls()
        snapshots = created or list(self.crawl.snapshot_set.filter(depth=0).order_by("created_at"))
        return [str(snapshot.id) for snapshot in snapshots]

    def _initial_snapshot_ids(self) -> list[str]:
        if self.initial_snapshot_ids:
            return [str(snapshot_id) for snapshot_id in self.initial_snapshot_ids]
        return self._create_root_snapshots()

    def _snapshot_config(self, snapshot) -> dict[str, Any]:
        from archivebox.config.configset import get_config

        config = get_config(crawl=self.crawl, snapshot=snapshot)
        config.update(self.base_config)
        config["CRAWL_DIR"] = str(self.crawl.output_dir)
        config["SNAP_DIR"] = str(snapshot.output_dir)
        config["SNAPSHOT_ID"] = str(snapshot.id)
        config["SNAPSHOT_DEPTH"] = snapshot.depth
        config["CRAWL_ID"] = str(self.crawl.id)
        config["SOURCE_URL"] = snapshot.url
        if snapshot.parent_snapshot_id:
            config["PARENT_SNAPSHOT_ID"] = str(snapshot.parent_snapshot_id)
        return config

    async def _run_install_crawl(self) -> None:
        install_snapshot = AbxSnapshot(
            url=self.primary_url or INSTALL_URL,
            id=str(self.crawl.id),
            crawl_id=str(self.crawl.id),
        )
        await download(
            url=self.primary_url or INSTALL_URL,
            plugins=self.plugins,
            output_dir=Path(self.crawl.output_dir),
            selected_plugins=self.selected_plugins,
            config_overrides={
                **self.base_config,
                "CRAWL_DIR": str(self.crawl.output_dir),
                "SNAP_DIR": str(self.crawl.output_dir),
                "CRAWL_ID": str(self.crawl.id),
                "SOURCE_URL": self.crawl.urls,
            },
            bus=self.bus,
            emit_jsonl=False,
            snapshot=install_snapshot,
            crawl_only=True,
        )

    async def _run_crawl_setup(self, snapshot_id: str) -> None:
        from asgiref.sync import sync_to_async

        snapshot = await sync_to_async(self._load_snapshot_run_data, thread_sensitive=True)(snapshot_id)
        setup_snapshot = AbxSnapshot(
            url=snapshot["url"],
            id=snapshot["id"],
            title=snapshot["title"],
            timestamp=snapshot["timestamp"],
            bookmarked_at=snapshot["bookmarked_at"],
            created_at=snapshot["created_at"],
            tags=snapshot["tags"],
            depth=snapshot["depth"],
            parent_snapshot_id=snapshot["parent_snapshot_id"],
            crawl_id=str(self.crawl.id),
        )
        await download(
            url=snapshot["url"],
            plugins=self.plugins,
            output_dir=Path(snapshot["output_dir"]),
            selected_plugins=self.selected_plugins,
            config_overrides=snapshot["config"],
            bus=self.bus,
            emit_jsonl=False,
            snapshot=setup_snapshot,
            crawl_setup_only=True,
        )

    async def _run_crawl_cleanup(self, snapshot_id: str) -> None:
        from asgiref.sync import sync_to_async

        snapshot = await sync_to_async(self._load_snapshot_run_data, thread_sensitive=True)(snapshot_id)
        cleanup_snapshot = AbxSnapshot(
            url=snapshot["url"],
            id=snapshot["id"],
            title=snapshot["title"],
            timestamp=snapshot["timestamp"],
            bookmarked_at=snapshot["bookmarked_at"],
            created_at=snapshot["created_at"],
            tags=snapshot["tags"],
            depth=snapshot["depth"],
            parent_snapshot_id=snapshot["parent_snapshot_id"],
            crawl_id=str(self.crawl.id),
        )
        await download(
            url=snapshot["url"],
            plugins=self.plugins,
            output_dir=Path(snapshot["output_dir"]),
            selected_plugins=self.selected_plugins,
            config_overrides=snapshot["config"],
            bus=self.bus,
            emit_jsonl=False,
            snapshot=cleanup_snapshot,
            crawl_cleanup_only=True,
        )

    async def _run_snapshot(self, snapshot_id: str) -> None:
        from asgiref.sync import sync_to_async

        async with self.snapshot_semaphore:
            snapshot = await sync_to_async(self._load_snapshot_run_data, thread_sensitive=True)(snapshot_id)
            abx_snapshot = AbxSnapshot(
                url=snapshot["url"],
                id=snapshot["id"],
                title=snapshot["title"],
                timestamp=snapshot["timestamp"],
                bookmarked_at=snapshot["bookmarked_at"],
                created_at=snapshot["created_at"],
                tags=snapshot["tags"],
                depth=snapshot["depth"],
                parent_snapshot_id=snapshot["parent_snapshot_id"],
                crawl_id=str(self.crawl.id),
            )
            await download(
                url=snapshot["url"],
                plugins=self.plugins,
                output_dir=Path(snapshot["output_dir"]),
                selected_plugins=self.selected_plugins,
                config_overrides=snapshot["config"],
                bus=self.bus,
                emit_jsonl=False,
                snapshot=abx_snapshot,
                skip_crawl_setup=True,
                skip_crawl_cleanup=True,
            )

    def _load_snapshot_run_data(self, snapshot_id: str):
        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.select_related("crawl").get(id=snapshot_id)
        return {
            "id": str(snapshot.id),
            "url": snapshot.url,
            "title": snapshot.title,
            "timestamp": snapshot.timestamp,
            "bookmarked_at": snapshot.bookmarked_at.isoformat() if snapshot.bookmarked_at else "",
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else "",
            "tags": snapshot.tags_str(),
            "depth": snapshot.depth,
            "parent_snapshot_id": str(snapshot.parent_snapshot_id) if snapshot.parent_snapshot_id else None,
            "output_dir": str(snapshot.output_dir),
            "config": self._snapshot_config(snapshot),
        }


def run_crawl(crawl_id: str, *, snapshot_ids: list[str] | None = None, selected_plugins: list[str] | None = None) -> None:
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.get(id=crawl_id)
    asyncio.run(CrawlRunner(crawl, snapshot_ids=snapshot_ids, selected_plugins=selected_plugins).run())


async def _run_binary(binary_id: str) -> None:
    from asgiref.sync import sync_to_async

    from archivebox.config.configset import get_config
    from archivebox.machine.models import Binary

    binary = await sync_to_async(Binary.objects.get, thread_sensitive=True)(id=binary_id)
    config = get_config()
    plugins = discover_plugins()
    bus = create_bus(name=_bus_name("ArchiveBox_binary", str(binary.id)), total_timeout=1800.0)
    setup_abx_services(
        bus,
        plugins=plugins,
        config_overrides=config,
        auto_install=True,
        emit_jsonl=False,
    )
    process_service = ProcessService(bus)
    MachineService(bus)
    BinaryService(bus)
    TagService(bus)
    ArchiveResultService(bus, process_service=process_service)

    try:
        _attach_bus_trace(bus)
        await bus.emit(
            BinaryEvent(
                name=binary.name,
                plugin_name="archivebox",
                hook_name="archivebox_run",
                output_dir=str(binary.output_dir),
                binary_id=str(binary.id),
                machine_id=str(binary.machine_id),
                abspath=binary.abspath,
                version=binary.version,
                sha256=binary.sha256,
                binproviders=binary.binproviders,
                binprovider=binary.binprovider,
                overrides=binary.overrides or None,
            ),
        )
    finally:
        await _stop_bus_trace(bus)
        await bus.stop()


def run_binary(binary_id: str) -> None:
    asyncio.run(_run_binary(binary_id))


async def _run_install(plugin_names: list[str] | None = None) -> None:
    from archivebox.config.configset import get_config

    config = get_config()
    plugins = discover_plugins()
    bus = create_bus(name="ArchiveBox_install", total_timeout=3600.0)
    abx_services = setup_abx_services(
        bus,
        plugins=plugins,
        config_overrides=config,
        auto_install=True,
        emit_jsonl=False,
    )
    process_service = ProcessService(bus)
    MachineService(bus)
    BinaryService(bus)
    TagService(bus)
    ArchiveResultService(bus, process_service=process_service)

    try:
        _attach_bus_trace(bus)
        await abx_install_plugins(
            plugin_names=plugin_names,
            plugins=plugins,
            config_overrides=config,
            emit_jsonl=False,
            bus=bus,
        )
        await abx_services.process.wait_for_background_monitors()
    finally:
        await _stop_bus_trace(bus)
        await bus.stop()


def run_install(*, plugin_names: list[str] | None = None) -> None:
    asyncio.run(_run_install(plugin_names=plugin_names))


def run_pending_crawls(*, daemon: bool = False, crawl_id: str | None = None) -> int:
    from archivebox.crawls.models import Crawl, CrawlSchedule
    from archivebox.machine.models import Binary

    while True:
        if daemon and crawl_id is None:
            now = timezone.now()
            for schedule in CrawlSchedule.objects.filter(is_enabled=True).select_related("template", "template__created_by"):
                if schedule.is_due(now):
                    schedule.enqueue(queued_at=now)

        if crawl_id is None:
            binary = (
                Binary.objects.filter(retry_at__lte=timezone.now())
                .exclude(status=Binary.StatusChoices.INSTALLED)
                .order_by("retry_at", "created_at")
                .first()
            )
            if binary is not None:
                run_binary(str(binary.id))
                continue

        pending = Crawl.objects.filter(retry_at__lte=timezone.now()).exclude(status=Crawl.StatusChoices.SEALED)
        if crawl_id:
            pending = pending.filter(id=crawl_id)
        pending = pending.order_by("retry_at", "created_at")

        crawl = pending.first()
        if crawl is None:
            if daemon:
                time.sleep(2.0)
                continue
            return 0

        run_crawl(str(crawl.id))
