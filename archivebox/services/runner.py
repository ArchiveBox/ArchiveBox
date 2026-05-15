from __future__ import annotations

import asyncio
import contextvars
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from asgiref.sync import sync_to_async
from django.utils import timezone
from rich.console import Console

from abx_dl.events import (
    BinaryRequestEvent,
    CrawlCleanupEvent,
    CrawlEvent,
    CrawlStartEvent,
    InstallEvent,
    MachineEvent,
    ProcessCompletedEvent,
    ProcessEvent,
    SnapshotCompletedEvent,
    SnapshotEvent,
    slow_warning_timeout,
)
from abx_dl.heartbeat import CrawlHeartbeat
from abx_dl.limits import CrawlLimitState
from abx_dl.models import Plugin, Snapshot as AbxSnapshot, discover_plugins, filter_plugins
from abx_dl.orchestrator import (
    compute_install_phase_timeout,
    compute_phase_timeout,
    create_bus,
    get_install_plugins,
    install_plugins as abx_install_plugins,
    setup_services as setup_abx_services,
)
from abx_dl.services.process_service import ProcessService as HookProcessService
from abx_dl.services.binary_service import BinaryService as HookBinaryService
from abx_dl.services.snapshot_service import SnapshotService as HookSnapshotService
from abxbus.event_bus import EventBus

from .archive_result_service import ArchiveResultService
from .binary_service import BinaryService
from .crawl_service import CrawlService
from .machine_service import MachineService
from .process_service import ProcessService as PersistedProcessService
from .snapshot_service import SnapshotService
from .tag_service import TagService
from .live_ui import LiveBusUI


def _bus_name(prefix: str, identifier: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in identifier)
    return f"{prefix}_{normalized}"


def _count_selected_hooks(plugins: dict[str, Plugin], selected_plugins: list[str] | None) -> int:
    selected = filter_plugins(plugins, selected_plugins) if selected_plugins else plugins
    return sum(1 for plugin in selected.values() for hook in plugin.hooks if "CrawlSetup" in hook.name or "Snapshot" in hook.name)


def _normalize_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in json.loads(json.dumps(config, default=str)).items() if value is not None}


def _runner_task_context() -> contextvars.Context:
    context = contextvars.copy_context()
    context.run(EventBus.current_event_context.set, None)
    context.run(EventBus.current_handler_id_context.set, None)
    context.run(EventBus.current_eventbus_context.set, None)
    return context


async def _emit_machine_config(
    bus,
    *,
    config: dict[str, Any],
    derived_config: dict[str, Any],
) -> None:
    user_config = _normalize_runtime_config(config)
    derived_machine_config = _normalize_runtime_config(derived_config)
    await bus.emit(
        MachineEvent(
            config=user_config,
            config_type="user",
        ),
    ).now()
    if derived_machine_config:
        await bus.emit(
            MachineEvent(
                config=derived_machine_config,
                config_type="derived",
            ),
        ).now()


def ensure_background_runner(*, allow_under_pytest: bool = False) -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST") and not allow_under_pytest:
        return False

    from archivebox.config import CONSTANTS
    from archivebox.machine.models import Machine, Process

    Process.cleanup_stale_running()
    Process.cleanup_orphaned_workers()
    machine = Machine.current()
    if Process.objects.filter(
        machine=machine,
        status=Process.StatusChoices.RUNNING,
        process_type=Process.TypeChoices.ORCHESTRATOR,
    ).exists():
        return False

    log_path = CONSTANTS.LOGS_DIR / "errors.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("DATA_DIR", str(CONSTANTS.DATA_DIR))

    with log_path.open("a", encoding="utf-8") as log_handle:
        subprocess.Popen(
            [sys.executable, "-m", "archivebox", "run", "--daemon"],
            cwd=str(CONSTANTS.DATA_DIR),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    return True


class CrawlRunner:
    MAX_CONCURRENT_SNAPSHOTS = 8

    def __init__(
        self,
        crawl,
        *,
        snapshot_ids: list[str] | None = None,
        selected_plugins: list[str] | None = None,
        process_discovered_snapshots_inline: bool = True,
    ):
        self.crawl = crawl
        self.bus = create_bus(name=_bus_name("ArchiveBox", str(crawl.id)), total_timeout=3600.0)
        self.plugins = discover_plugins()
        HookProcessService(self.bus, emit_jsonl=False, interactive_tty=False)
        PersistedProcessService(self.bus)
        BinaryService(self.bus)
        TagService(self.bus)
        CrawlService(self.bus, crawl_id=str(crawl.id))
        MachineService(self.bus)
        self.process_discovered_snapshots_inline = process_discovered_snapshots_inline

        async def ignore_snapshot(_snapshot_id: str) -> None:
            return None

        SnapshotService(
            self.bus,
            crawl_id=str(crawl.id),
            schedule_snapshot=self.enqueue_snapshot if process_discovered_snapshots_inline else ignore_snapshot,
        )
        ArchiveResultService(self.bus)
        self.selected_plugins = selected_plugins
        self.initial_snapshot_ids = snapshot_ids
        self.snapshot_tasks: dict[str, asyncio.Task[None]] = {}
        self.snapshot_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_SNAPSHOTS)
        self.persona = None
        self.base_config: dict[str, Any] = {}
        self.derived_config: dict[str, Any] = {}
        self.primary_url = ""
        self.crawl_output_dir = ""
        self._live_stream = None
        self.root_crawl_event_id: str | None = None

    def runtime_plugins(self) -> dict[str, Plugin]:
        return filter_plugins(self.plugins, self.selected_plugins, include_providers=True) if self.selected_plugins else self.plugins

    async def run(self) -> None:
        heartbeat = CrawlHeartbeat(
            Path(self.crawl_output_dir),
            runtime="archivebox",
            crawl_id=str(self.crawl.id),
        )
        try:
            snapshot_ids = await sync_to_async(self.load_run_state, thread_sensitive=True)()
            live_ui = self._create_live_ui()
            with live_ui if live_ui is not None else nullcontext():
                await heartbeat.start()
                await _emit_machine_config(
                    self.bus,
                    config={
                        **self.base_config,
                        "ABX_RUNTIME": "archivebox",
                    },
                    derived_config=self.derived_config,
                )
                if snapshot_ids:
                    root_snapshot_id = snapshot_ids[0]
                    await self.run_crawl_setup(root_snapshot_id)
                    for snapshot_id in snapshot_ids:
                        await self.enqueue_snapshot(snapshot_id)
                    await self.wait_for_snapshot_tasks()
                    await self.run_crawl_cleanup(root_snapshot_id)
        finally:
            await heartbeat.stop()
            await self.bus.wait_until_idle()
            if self._live_stream is not None:
                try:
                    self._live_stream.close()
                except Exception:
                    pass
                self._live_stream = None
            await sync_to_async(self.finalize_run_state, thread_sensitive=True)()

    async def enqueue_snapshot(self, snapshot_id: str) -> None:
        task = self.snapshot_tasks.get(snapshot_id)
        if task is not None and not task.done():
            return
        task = asyncio.create_task(self.run_snapshot(snapshot_id), context=_runner_task_context())
        self.snapshot_tasks[snapshot_id] = task

    async def wait_for_snapshot_tasks(self) -> None:
        while True:
            pending_tasks: list[asyncio.Task[None]] = []
            for snapshot_id, task in list(self.snapshot_tasks.items()):
                if task.done():
                    if self.snapshot_tasks.get(snapshot_id) is task:
                        self.snapshot_tasks.pop(snapshot_id, None)
                    task.result()
                    continue
                pending_tasks.append(task)
            if not pending_tasks:
                return
            done, _pending = await asyncio.wait(pending_tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()

    def load_run_state(self) -> list[str]:
        from archivebox.config.configset import get_config
        from archivebox.hooks import discover_hooks
        from archivebox.machine.models import Machine, NetworkInterface, Process

        self.primary_url = self.crawl.get_urls_list()[0] if self.crawl.get_urls_list() else ""
        current_iface = NetworkInterface.current(refresh=True)
        current_process = Process.current()
        if current_process.iface_id != current_iface.id or current_process.machine_id != current_iface.machine_id:
            current_process.iface = current_iface
            current_process.machine = current_iface.machine
            current_process.save(update_fields=["iface", "machine", "modified_at"])
        self.persona = self.crawl.resolve_persona()
        self.base_config = get_config(crawl=self.crawl)
        self.derived_config = dict(Machine.current().config)
        self.crawl_output_dir = str(self.crawl.output_dir)
        self.base_config["ABX_RUNTIME"] = "archivebox"
        self.base_config["CHROME_ISOLATION"] = "snapshot"
        if self.selected_plugins is None:
            raw_plugins = str(self.base_config.get("PLUGINS") or "").strip()
            if raw_plugins:
                self.selected_plugins = [name.strip() for name in raw_plugins.split(",") if name.strip()]
            else:
                runtime_events = ("CrawlSetup", "CrawlCleanup", "Snapshot", "SnapshotCleanup")
                runtime_plugins = {
                    hook.parent.name for event_name in runtime_events for hook in discover_hooks(event_name, config=self.base_config)
                }
                self.selected_plugins = sorted(runtime_plugins) or None
        if self.persona:
            self.base_config.update(
                self.persona.prepare_runtime_for_crawl(
                    self.crawl,
                    chrome_binary=self.base_config["CHROME_BINARY"],
                ),
            )
        if self.initial_snapshot_ids:
            return [str(snapshot_id) for snapshot_id in self.initial_snapshot_ids]
        pending_snapshots = list(
            self.crawl.snapshot_set.exclude(status="sealed").order_by("depth", "created_at"),
        )
        if pending_snapshots:
            return [str(snapshot.id) for snapshot in pending_snapshots]
        created = self.crawl.create_snapshots_from_urls()
        snapshots = created or list(self.crawl.snapshot_set.filter(depth=0).order_by("created_at"))
        return [str(snapshot.id) for snapshot in snapshots]

    def finalize_run_state(self) -> None:
        from archivebox.crawls.models import Crawl

        if self.persona:
            self.persona.cleanup_runtime_for_crawl(self.crawl)
        crawl = Crawl.objects.get(id=self.crawl.id)
        if crawl.is_finished():
            if crawl.status != Crawl.StatusChoices.SEALED:
                crawl.status = Crawl.StatusChoices.SEALED
                crawl.retry_at = None
                crawl.save(update_fields=["status", "retry_at", "modified_at"])
            return
        if crawl.status == Crawl.StatusChoices.SEALED:
            crawl.status = Crawl.StatusChoices.QUEUED
        elif crawl.status != Crawl.StatusChoices.STARTED:
            crawl.status = Crawl.StatusChoices.STARTED
        crawl.retry_at = crawl.retry_at or timezone.now()
        crawl.save(update_fields=["status", "retry_at", "modified_at"])

    def _create_live_ui(self) -> LiveBusUI | None:
        stdout_is_tty = sys.stdout.isatty()
        stderr_is_tty = sys.stderr.isatty()
        interactive_tty = stdout_is_tty or stderr_is_tty
        if not interactive_tty:
            return None
        stream = sys.stderr if stderr_is_tty else sys.stdout
        if os.path.exists("/dev/tty"):
            try:
                self._live_stream = open("/dev/tty", "w", buffering=1, encoding=stream.encoding or "utf-8")
                stream = self._live_stream
            except OSError:
                self._live_stream = None
        try:
            terminal_size = os.get_terminal_size(stream.fileno())
            terminal_width = terminal_size.columns
            terminal_height = terminal_size.lines
        except (AttributeError, OSError, ValueError):
            terminal_size = shutil.get_terminal_size(fallback=(160, 40))
            terminal_width = terminal_size.columns
            terminal_height = terminal_size.lines
        ui_console = Console(
            file=stream,
            force_terminal=True,
            width=terminal_width,
            height=terminal_height,
            _environ={
                "COLUMNS": str(terminal_width),
                "LINES": str(terminal_height),
            },
        )
        plugins_label = ", ".join(self.selected_plugins) if self.selected_plugins else f"all ({len(self.plugins)} available)"
        live_ui = LiveBusUI(
            self.bus,
            total_hooks=_count_selected_hooks(self.plugins, self.selected_plugins),
            timeout_seconds=self.base_config["TIMEOUT"],
            ui_console=ui_console,
            interactive_tty=True,
        )
        live_ui.print_intro(
            url=self.primary_url or "crawl",
            output_dir=Path(self.crawl_output_dir),
            plugins_label=plugins_label,
        )
        return live_ui

    def load_snapshot_payload(self, snapshot_id: str) -> dict[str, Any]:
        from archivebox.core.models import Snapshot
        from archivebox.config.configset import get_config

        snapshot = Snapshot.objects.select_related("crawl").get(id=snapshot_id)
        config = get_config(crawl=self.crawl, snapshot=snapshot)
        config.update(self.base_config)
        config["CRAWL_DIR"] = self.crawl_output_dir
        config["SNAP_DIR"] = str(snapshot.output_dir)
        extra_context: dict[str, Any] = {}
        if config.get("EXTRA_CONTEXT"):
            parsed_extra_context = json.loads(str(config["EXTRA_CONTEXT"]))
            if not isinstance(parsed_extra_context, dict):
                raise TypeError("EXTRA_CONTEXT must decode to an object")
            extra_context = parsed_extra_context
        extra_context["snapshot_id"] = str(snapshot.id)
        extra_context["snapshot_depth"] = snapshot.depth
        config["EXTRA_CONTEXT"] = json.dumps(extra_context, separators=(",", ":"), sort_keys=True)
        return {
            "id": str(snapshot.id),
            "url": snapshot.url,
            "title": snapshot.title,
            "timestamp": snapshot.timestamp,
            "bookmarked_at": snapshot.bookmarked_at.isoformat() if snapshot.bookmarked_at else "",
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else "",
            "tags": snapshot.tags_str(),
            "depth": snapshot.depth,
            "status": snapshot.status,
            "output_dir": str(snapshot.output_dir),
            "config": config,
            "_snapshot": snapshot,
        }

    async def enqueue_discovered_snapshots_from_outputs(self, snapshot_payload: dict[str, Any]) -> None:
        from archivebox.core.models import Snapshot
        from archivebox.hooks import collect_urls_from_plugins

        if int(snapshot_payload["depth"]) >= self.crawl.max_depth:
            return
        if CrawlLimitState.from_config(snapshot_payload["config"]).get_stop_reason() == "max_size":
            return

        discovered_urls = await sync_to_async(collect_urls_from_plugins, thread_sensitive=True)(Path(snapshot_payload["output_dir"]))
        if not discovered_urls:
            return

        parent_snapshot = snapshot_payload.get("_snapshot")
        if parent_snapshot is None:
            parent_snapshot = await sync_to_async(
                lambda: Snapshot.objects.select_related("crawl", "crawl__created_by").filter(id=snapshot_payload["id"]).first(),
                thread_sensitive=True,
            )()
        if parent_snapshot is None:
            return

        for record in discovered_urls:
            url = str(record.get("url") or "").strip()
            if not url:
                continue
            child_snapshot = await sync_to_async(self.crawl.create_discovered_snapshot, thread_sensitive=True)(
                parent_snapshot,
                url=url,
                depth=parent_snapshot.depth + 1,
                title=str(record.get("title") or "").strip(),
                tags=str(record.get("tags") or "").strip(),
            )
            if child_snapshot is None:
                has_capacity = await sync_to_async(self.crawl.has_remaining_snapshot_capacity, thread_sensitive=True)()
                if has_capacity:
                    continue
                break
            if self.process_discovered_snapshots_inline:
                await self.enqueue_snapshot(str(child_snapshot.id))

    async def run_crawl_setup(self, snapshot_id: str) -> None:
        snapshot = await sync_to_async(self.load_snapshot_payload, thread_sensitive=True)(snapshot_id)
        config = _normalize_runtime_config(snapshot["config"])
        derived_config = _normalize_runtime_config(self.derived_config)
        output_dir = Path(self.crawl_output_dir)
        plugins = self.runtime_plugins()
        abx_snapshot = AbxSnapshot(
            id=snapshot["id"],
            url=snapshot["url"],
            depth=int(snapshot["depth"]),
            crawl_id=str(self.crawl.id),
        )
        setup_hooks = [(plugin, hook) for plugin in plugins.values() for hook in plugin.filter_hooks("CrawlSetup")]
        crawl_setup_phase_timeout = compute_phase_timeout(setup_hooks, config)
        install_phase_timeout = compute_install_phase_timeout(get_install_plugins(plugins), config)
        await _emit_machine_config(self.bus, config=config, derived_config=derived_config)
        setup_abx_services(
            self.bus,
            plugins=plugins,
            url=snapshot["url"],
            snapshot=abx_snapshot,
            output_dir=output_dir,
            install_enabled=False,
            crawl_setup_enabled=True,
            crawl_start_enabled=False,
            snapshot_cleanup_enabled=False,
            crawl_cleanup_enabled=False,
            crawl_setup_phase_timeout=crawl_setup_phase_timeout,
            snapshot_phase_timeout=0.0,
            snapshot_cleanup_phase_timeout=0.0,
            crawl_cleanup_phase_timeout=crawl_setup_phase_timeout,
            persist_derived=False,
            auto_install=True,
            emit_jsonl=False,
            MachineService=None,
            BinaryService=HookBinaryService,
            ProcessService=None,
            ArchiveResultService=None,
            TagService=None,
            SnapshotService=None,
        )
        install_event = self.bus.emit(
            InstallEvent(
                url=snapshot["url"],
                snapshot_id=snapshot["id"],
                output_dir=str(output_dir),
                event_timeout=install_phase_timeout,
                event_handler_slow_timeout=slow_warning_timeout(install_phase_timeout),
            ),
        )
        await install_event.now()
        await install_event.wait()
        crawl_event = CrawlEvent(
            url=snapshot["url"],
            snapshot_id=snapshot["id"],
            output_dir=str(output_dir),
            event_timeout=crawl_setup_phase_timeout,
            event_handler_slow_timeout=slow_warning_timeout(crawl_setup_phase_timeout),
        )
        self.root_crawl_event_id = crawl_event.event_id
        await self.bus.emit(crawl_event).now()
        for plugin, hook in setup_hooks:
            if hook.is_background:
                continue
            process_event = await self.bus.find(
                ProcessEvent,
                past=True,
                future=crawl_setup_phase_timeout,
                where=lambda candidate, plugin_name=plugin.name, hook_name=hook.name: (
                    self.bus.event_is_child_of(candidate, crawl_event)
                    and candidate.plugin_name == plugin_name
                    and candidate.hook_name == hook_name
                    and candidate.output_dir == str(output_dir / plugin_name)
                ),
            )
            if process_event is None:
                raise RuntimeError(f"Crawl setup hook {plugin.name}:{hook.name} did not start")
            completed_process = await self.bus.find(
                ProcessCompletedEvent,
                child_of=process_event,
                past=True,
                future=crawl_setup_phase_timeout,
            )
            if completed_process is None:
                raise RuntimeError(f"Crawl setup hook {plugin.name}:{hook.name} did not complete")
            if completed_process.status == "failed":
                raise RuntimeError(f"Crawl setup hook {plugin.name}:{hook.name} failed")

    async def run_crawl_cleanup(self, snapshot_id: str) -> None:
        snapshot = await sync_to_async(self.load_snapshot_payload, thread_sensitive=True)(snapshot_id)
        if self.root_crawl_event_id is None:
            return
        config = _normalize_runtime_config(snapshot["config"])
        output_dir = Path(self.crawl_output_dir)
        plugins = self.runtime_plugins()
        setup_hooks = [(plugin, hook) for plugin in plugins.values() for hook in plugin.filter_hooks("CrawlSetup")]
        crawl_cleanup_phase_timeout = compute_phase_timeout(setup_hooks, config)
        await self.bus.emit(
            CrawlCleanupEvent(
                url=snapshot["url"],
                snapshot_id=snapshot["id"],
                output_dir=str(output_dir),
                event_parent_id=self.root_crawl_event_id,
                event_timeout=crawl_cleanup_phase_timeout,
                event_handler_slow_timeout=slow_warning_timeout(crawl_cleanup_phase_timeout),
            ),
        ).now()

    async def run_snapshot(self, snapshot_id: str) -> None:
        async with self.snapshot_semaphore:
            snapshot = await sync_to_async(self.load_snapshot_payload, thread_sensitive=True)(snapshot_id)
            if snapshot["status"] == "sealed":
                return
            if snapshot["depth"] > 0 and CrawlLimitState.from_config(snapshot["config"]).get_stop_reason() == "max_size":
                await sync_to_async(self.seal_snapshot_due_to_limit, thread_sensitive=True)(snapshot_id)
                return
            try:
                config = _normalize_runtime_config(snapshot["config"])
                derived_config = _normalize_runtime_config(self.derived_config)
                output_dir = Path(snapshot["output_dir"])
                plugins = self.runtime_plugins()
                abx_snapshot = AbxSnapshot(
                    id=snapshot["id"],
                    url=snapshot["url"],
                    depth=int(snapshot["depth"]),
                    crawl_id=str(self.crawl.id),
                )
                snapshot_hooks = [(plugin, hook) for plugin in plugins.values() for hook in plugin.filter_hooks("Snapshot")]
                snapshot_phase_timeout = compute_phase_timeout(snapshot_hooks, config)
                await _emit_machine_config(self.bus, config=config, derived_config=derived_config)
                HookSnapshotService(
                    self.bus,
                    url=snapshot["url"],
                    snapshot=abx_snapshot,
                    output_dir=output_dir,
                    plugins=plugins,
                    snapshot_phase_timeout=snapshot_phase_timeout,
                    snapshot_cleanup_enabled=True,
                    snapshot_cleanup_phase_timeout=snapshot_phase_timeout,
                )
                crawl_start_event = CrawlStartEvent(
                    url=snapshot["url"],
                    snapshot_id=snapshot["id"],
                    output_dir=str(output_dir),
                    event_timeout=snapshot_phase_timeout,
                    event_handler_slow_timeout=slow_warning_timeout(snapshot_phase_timeout),
                )
                await self.bus.emit(crawl_start_event).now()
                snapshot_event = SnapshotEvent(
                    url=snapshot["url"],
                    snapshot_id=snapshot["id"],
                    output_dir=str(output_dir),
                    depth=int(snapshot["depth"]),
                    event_parent_id=crawl_start_event.event_id,
                    event_timeout=snapshot_phase_timeout,
                    event_handler_slow_timeout=slow_warning_timeout(snapshot_phase_timeout),
                )
                emitted_snapshot_event = self.bus.emit(snapshot_event)
                await emitted_snapshot_event.now()
                completed_snapshot = await self.bus.find(
                    SnapshotCompletedEvent,
                    child_of=emitted_snapshot_event,
                    past=True,
                    future=snapshot_phase_timeout,
                )
                if completed_snapshot is None:
                    raise RuntimeError(f"Snapshot {snapshot_id} did not complete")
                await self.enqueue_discovered_snapshots_from_outputs(snapshot)
            finally:
                current_task = asyncio.current_task()
                if current_task is not None and self.snapshot_tasks.get(snapshot_id) is current_task:
                    self.snapshot_tasks.pop(snapshot_id, None)

    def seal_snapshot_due_to_limit(self, snapshot_id: str) -> None:
        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.filter(id=snapshot_id).first()
        if snapshot is None or snapshot.status == Snapshot.StatusChoices.SEALED:
            return
        snapshot.status = Snapshot.StatusChoices.SEALED
        snapshot.retry_at = None
        snapshot.save(update_fields=["status", "retry_at", "modified_at"])


def run_crawl(
    crawl_id: str,
    *,
    snapshot_ids: list[str] | None = None,
    selected_plugins: list[str] | None = None,
    process_discovered_snapshots_inline: bool = True,
) -> None:
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.get(id=crawl_id)
    asyncio.run(
        CrawlRunner(
            crawl,
            snapshot_ids=snapshot_ids,
            selected_plugins=selected_plugins,
            process_discovered_snapshots_inline=process_discovered_snapshots_inline,
        ).run(),
    )


async def _run_binary(binary_id: str) -> None:
    from archivebox.config.configset import get_config
    from archivebox.machine.models import Binary, Machine

    binary = await Binary.objects.aget(id=binary_id)
    plugins = discover_plugins()
    config = get_config()
    machine = await sync_to_async(Machine.current, thread_sensitive=True)()
    derived_config = _normalize_runtime_config(dict(machine.config))
    config["ABX_RUNTIME"] = "archivebox"
    config = _normalize_runtime_config(config)
    bus = create_bus(name=_bus_name("ArchiveBox_binary", str(binary.id)), total_timeout=1800.0)
    PersistedProcessService(bus)
    BinaryService(bus)
    TagService(bus)
    ArchiveResultService(bus)
    MachineService(bus)
    setup_abx_services(
        bus,
        plugins=plugins,
        install_enabled=False,
        crawl_setup_enabled=False,
        crawl_start_enabled=False,
        snapshot_cleanup_enabled=False,
        crawl_cleanup_enabled=False,
        persist_derived=False,
        auto_install=True,
        emit_jsonl=False,
    )
    await _emit_machine_config(bus, config=config, derived_config=derived_config)

    try:
        await bus.emit(
            BinaryRequestEvent(
                name=binary.name,
                plugin_name="archivebox",
                hook_name="on_BinaryRequest__archivebox_run",
                output_dir=str(binary.output_dir),
                binary_id=str(binary.id),
                machine_id=str(binary.machine_id),
                binproviders=binary.binproviders,
                overrides=binary.overrides or None,
            ),
        ).now(first_result=True)
    finally:
        await bus.wait_until_idle()


def run_binary(binary_id: str) -> None:
    asyncio.run(_run_binary(binary_id))


async def _run_install(plugin_names: list[str] | None = None) -> None:
    from archivebox.config.configset import get_config
    from archivebox.machine.models import Machine

    plugins = discover_plugins()
    config = get_config()
    machine = await sync_to_async(Machine.current, thread_sensitive=True)()
    derived_config = _normalize_runtime_config(dict(machine.config))
    config["ABX_RUNTIME"] = "archivebox"
    config = _normalize_runtime_config(config)
    bus = create_bus(name="ArchiveBox_install", total_timeout=3600.0)
    PersistedProcessService(bus)
    BinaryService(bus)
    TagService(bus)
    ArchiveResultService(bus)
    MachineService(bus)
    await _emit_machine_config(bus, config=config, derived_config=derived_config)
    live_stream = None

    try:
        selected_plugins = filter_plugins(plugins, list(plugin_names), include_providers=True) if plugin_names else plugins
        if not selected_plugins:
            return
        plugins_label = ", ".join(plugin_names) if plugin_names else f"all ({len(plugins)} available)"
        timeout_seconds = config["TIMEOUT"]
        stdout_is_tty = sys.stdout.isatty()
        stderr_is_tty = sys.stderr.isatty()
        interactive_tty = stdout_is_tty or stderr_is_tty
        ui_console = None
        live_ui = None

        if interactive_tty:
            stream = sys.stderr if stderr_is_tty else sys.stdout
            if os.path.exists("/dev/tty"):
                try:
                    live_stream = open("/dev/tty", "w", buffering=1, encoding=stream.encoding or "utf-8")
                    stream = live_stream
                except OSError:
                    live_stream = None
            try:
                terminal_size = os.get_terminal_size(stream.fileno())
                terminal_width = terminal_size.columns
                terminal_height = terminal_size.lines
            except (AttributeError, OSError, ValueError):
                terminal_size = shutil.get_terminal_size(fallback=(160, 40))
                terminal_width = terminal_size.columns
                terminal_height = terminal_size.lines
            ui_console = Console(
                file=stream,
                force_terminal=True,
                width=terminal_width,
                height=terminal_height,
                _environ={
                    "COLUMNS": str(terminal_width),
                    "LINES": str(terminal_height),
                },
            )

        with TemporaryDirectory(prefix="archivebox-install-") as temp_dir:
            output_dir = Path(temp_dir)
            if ui_console is not None:
                live_ui = LiveBusUI(
                    bus,
                    total_hooks=_count_selected_hooks(selected_plugins, None),
                    timeout_seconds=timeout_seconds,
                    ui_console=ui_console,
                    interactive_tty=interactive_tty,
                )
                live_ui.print_intro(
                    url="install",
                    output_dir=output_dir,
                    plugins_label=plugins_label,
                )
            with live_ui if live_ui is not None else nullcontext():
                await abx_install_plugins(
                    plugin_names=plugin_names,
                    plugins=plugins,
                    output_dir=output_dir,
                    config_overrides=config,
                    derived_config_overrides=derived_config,
                    emit_jsonl=False,
                    bus=bus,
                    MachineService=None,
                )
            if live_ui is not None:
                live_ui.print_summary(output_dir=output_dir)
    finally:
        await bus.wait_until_idle()
        try:
            if live_stream is not None:
                live_stream.close()
        except Exception:
            pass


def run_install(*, plugin_names: list[str] | None = None) -> None:
    asyncio.run(_run_install(plugin_names=plugin_names))


def recover_orphaned_crawls() -> int:
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Process

    active_crawl_ids: set[str] = set()
    orphaned_crawls = list(
        Crawl.objects.filter(
            status=Crawl.StatusChoices.STARTED,
            retry_at__isnull=True,
        ).prefetch_related("snapshot_set"),
    )
    running_processes = Process.objects.filter(
        status=Process.StatusChoices.RUNNING,
        process_type__in=[
            Process.TypeChoices.WORKER,
            Process.TypeChoices.HOOK,
            Process.TypeChoices.BINARY,
        ],
    ).only("pwd")

    for proc in running_processes:
        if not proc.pwd:
            continue
        proc_pwd = Path(proc.pwd)
        for crawl in orphaned_crawls:
            matched_snapshot = None
            for snapshot in crawl.snapshot_set.all():
                try:
                    proc_pwd.relative_to(snapshot.output_dir)
                    matched_snapshot = snapshot
                    break
                except ValueError:
                    continue
            if matched_snapshot is not None:
                active_crawl_ids.add(str(crawl.id))
                break

    recovered = 0
    now = timezone.now()
    for crawl in orphaned_crawls:
        if str(crawl.id) in active_crawl_ids:
            continue

        snapshots = list(crawl.snapshot_set.all())
        if not snapshots or all(snapshot.status == Snapshot.StatusChoices.SEALED for snapshot in snapshots):
            crawl.status = Crawl.StatusChoices.SEALED
            crawl.retry_at = None
            crawl.save(update_fields=["status", "retry_at", "modified_at"])
            recovered += 1
            continue

        crawl.retry_at = now
        crawl.save(update_fields=["retry_at", "modified_at"])
        recovered += 1

    return recovered


def recover_orphaned_snapshots() -> int:
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Process

    active_snapshot_ids: set[str] = set()
    orphaned_snapshots = list(
        Snapshot.objects.filter(status=Snapshot.StatusChoices.STARTED, retry_at__isnull=True)
        .select_related("crawl")
        .prefetch_related("archiveresult_set"),
    )
    running_processes = Process.objects.filter(
        status=Process.StatusChoices.RUNNING,
        process_type__in=[
            Process.TypeChoices.WORKER,
            Process.TypeChoices.HOOK,
            Process.TypeChoices.BINARY,
        ],
    ).only("pwd")

    for proc in running_processes:
        if not proc.pwd:
            continue
        proc_pwd = Path(proc.pwd)
        for snapshot in orphaned_snapshots:
            try:
                proc_pwd.relative_to(snapshot.output_dir)
                active_snapshot_ids.add(str(snapshot.id))
                break
            except ValueError:
                continue

    recovered = 0
    now = timezone.now()
    for snapshot in orphaned_snapshots:
        if str(snapshot.id) in active_snapshot_ids:
            continue

        results = list(snapshot.archiveresult_set.all())
        if results and all(result.status in ArchiveResult.FINAL_STATES for result in results):
            snapshot.status = Snapshot.StatusChoices.SEALED
            snapshot.retry_at = None
            snapshot.downloaded_at = snapshot.downloaded_at or now
            snapshot.save(update_fields=["status", "retry_at", "downloaded_at", "modified_at"])

            crawl = snapshot.crawl
            if crawl.is_finished() and crawl.status != Crawl.StatusChoices.SEALED:
                crawl.status = Crawl.StatusChoices.SEALED
                crawl.retry_at = None
                crawl.save(update_fields=["status", "retry_at", "modified_at"])
            recovered += 1
            continue

        snapshot.status = Snapshot.StatusChoices.QUEUED
        snapshot.retry_at = now
        snapshot.save(update_fields=["status", "retry_at", "modified_at"])

        crawl = snapshot.crawl
        crawl.status = Crawl.StatusChoices.QUEUED
        crawl.retry_at = now
        crawl.save(update_fields=["status", "retry_at", "modified_at"])
        recovered += 1

    return recovered


def run_pending_crawls(*, daemon: bool = False, crawl_id: str | None = None) -> int:
    from archivebox.crawls.models import Crawl, CrawlSchedule
    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Binary

    while True:
        if daemon and crawl_id is None:
            now = timezone.now()
            for schedule in CrawlSchedule.objects.filter(is_enabled=True).select_related("template", "template__created_by"):
                if schedule.is_due(now):
                    schedule.enqueue(queued_at=now)

        queued_crawls = Crawl.objects.filter(
            retry_at__lte=timezone.now(),
            status=Crawl.StatusChoices.QUEUED,
        )
        if crawl_id:
            queued_crawls = queued_crawls.filter(id=crawl_id)
        queued_crawls = queued_crawls.order_by("retry_at", "created_at")

        queued_crawl = queued_crawls.first()
        if queued_crawl is not None:
            if not queued_crawl.claim_processing_lock(lock_seconds=60):
                continue
            run_crawl(str(queued_crawl.id), process_discovered_snapshots_inline=True)
            continue

        if crawl_id is None:
            snapshot = (
                Snapshot.objects.filter(retry_at__lte=timezone.now())
                .exclude(status=Snapshot.StatusChoices.SEALED)
                .select_related("crawl")
                .order_by("retry_at", "created_at")
                .first()
            )
            if snapshot is not None:
                if not snapshot.claim_processing_lock(lock_seconds=60):
                    continue
                run_crawl(
                    str(snapshot.crawl_id),
                    snapshot_ids=[str(snapshot.id)],
                    process_discovered_snapshots_inline=True,
                )
                continue

        if crawl_id is None:
            # Standalone binary backlog should not starve queued crawls or snapshots.
            # Crawl.run() already claims and installs crawl-declared Binary rows as needed.
            binary = (
                Binary.objects.filter(retry_at__lte=timezone.now())
                .exclude(status=Binary.StatusChoices.INSTALLED)
                .order_by("retry_at", "created_at")
                .first()
            )
            if binary is not None:
                if not binary.claim_processing_lock(lock_seconds=60):
                    continue
                run_binary(str(binary.id))
                continue

        pending = Crawl.objects.filter(
            retry_at__lte=timezone.now(),
            status=Crawl.StatusChoices.STARTED,
        )
        if crawl_id:
            pending = pending.filter(id=crawl_id)
        pending = pending.order_by("retry_at", "created_at")

        crawl = pending.first()
        if crawl is None:
            if daemon:
                time.sleep(2.0)
                continue
            return 0

        if not crawl.claim_processing_lock(lock_seconds=60):
            continue

        run_crawl(str(crawl.id), process_discovered_snapshots_inline=True)
