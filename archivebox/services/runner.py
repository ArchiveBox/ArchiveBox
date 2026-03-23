from __future__ import annotations

import asyncio
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

from django.utils import timezone
from rich.console import Console

from abx_dl.events import BinaryRequestEvent
from abx_dl.limits import CrawlLimitState
from abx_dl.models import Plugin, Snapshot as AbxSnapshot, discover_plugins, filter_plugins
from abx_dl.orchestrator import (
    create_bus,
    download,
    install_plugins as abx_install_plugins,
    setup_services as setup_abx_services,
)

from .archive_result_service import ArchiveResultService
from .binary_service import BinaryService
from .crawl_service import CrawlService
from .machine_service import MachineService
from .process_request_service import ProcessRequestService
from .process_service import ProcessService
from .snapshot_service import SnapshotService
from .tag_service import TagService
from .live_ui import LiveBusUI


def _bus_name(prefix: str, identifier: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in identifier)
    return f"{prefix}_{normalized}"


def _selected_plugins_from_config(config: dict[str, Any]) -> list[str] | None:
    raw = str(config.get("PLUGINS") or "").strip()
    if not raw:
        return None
    return [name.strip() for name in raw.split(",") if name.strip()]


def _count_selected_hooks(plugins: dict[str, Plugin], selected_plugins: list[str] | None) -> int:
    selected = filter_plugins(plugins, selected_plugins) if selected_plugins else plugins
    return sum(
        1
        for plugin in selected.values()
        for hook in plugin.hooks
        if "Install" in hook.name or "CrawlSetup" in hook.name or "Snapshot" in hook.name
    )


def _runner_debug(message: str) -> None:
    print(f"[runner] {message}", file=sys.stderr, flush=True)


def _binary_env_key(name: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in name).upper()
    return f"{normalized}_BINARY"


def _binary_config_keys_for_plugins(plugins: dict[str, Plugin], binary_name: str) -> list[str]:
    keys: list[str] = []
    if binary_name != "postlight-parser":
        keys.append(_binary_env_key(binary_name))

    for plugin in plugins.values():
        for key, prop in plugin.config_schema.items():
            if key.endswith("_BINARY") and prop.get("default") == binary_name:
                keys.insert(0, key)

    return list(dict.fromkeys(keys))


def _installed_binary_config_overrides(plugins: dict[str, Plugin]) -> dict[str, str]:
    from archivebox.machine.models import Binary, Machine

    machine = Machine.current()
    overrides: dict[str, str] = {}
    shared_lib_dir: Path | None = None
    pip_home: Path | None = None
    pip_bin_dir: Path | None = None
    npm_home: Path | None = None
    node_modules_dir: Path | None = None
    npm_bin_dir: Path | None = None
    binaries = (
        Binary.objects.filter(machine=machine, status=Binary.StatusChoices.INSTALLED).exclude(abspath="").exclude(abspath__isnull=True)
    )

    for binary in binaries:
        try:
            resolved_path = Path(binary.abspath).expanduser()
        except (TypeError, ValueError):
            continue
        if not resolved_path.is_file() or not os.access(resolved_path, os.X_OK):
            continue
        for key in _binary_config_keys_for_plugins(plugins, binary.name):
            overrides[key] = binary.abspath

        if resolved_path.parent.name == ".bin" and resolved_path.parent.parent.name == "node_modules":
            npm_bin_dir = npm_bin_dir or resolved_path.parent
            node_modules_dir = node_modules_dir or resolved_path.parent.parent
            npm_home = npm_home or resolved_path.parent.parent.parent
            shared_lib_dir = shared_lib_dir or resolved_path.parent.parent.parent.parent
        elif (
            resolved_path.parent.name == "bin"
            and resolved_path.parent.parent.name == "venv"
            and resolved_path.parent.parent.parent.name == "pip"
        ):
            pip_bin_dir = pip_bin_dir or resolved_path.parent
            pip_home = pip_home or resolved_path.parent.parent.parent
            shared_lib_dir = shared_lib_dir or resolved_path.parent.parent.parent.parent

    if shared_lib_dir is not None:
        overrides["LIB_DIR"] = str(shared_lib_dir)
        overrides["LIB_BIN_DIR"] = str(shared_lib_dir / "bin")
    if pip_home is not None:
        overrides["PIP_HOME"] = str(pip_home)
    if pip_bin_dir is not None:
        overrides["PIP_BIN_DIR"] = str(pip_bin_dir)
    if npm_home is not None:
        overrides["NPM_HOME"] = str(npm_home)
    if node_modules_dir is not None:
        overrides["NODE_MODULES_DIR"] = str(node_modules_dir)
        overrides["NODE_MODULE_DIR"] = str(node_modules_dir)
        overrides["NODE_PATH"] = str(node_modules_dir)
    if npm_bin_dir is not None:
        overrides["NPM_BIN_DIR"] = str(npm_bin_dir)

    return overrides


def _limit_stop_reason(config: dict[str, Any]) -> str:
    return CrawlLimitState.from_config(config).get_stop_reason()


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
        self.process_service = ProcessService(self.bus)
        self.machine_service = MachineService(self.bus)
        self.binary_service = BinaryService(self.bus)
        self.tag_service = TagService(self.bus)
        self.process_request_service = ProcessRequestService(self.bus)
        self.crawl_service = CrawlService(self.bus, crawl_id=str(crawl.id))
        self.process_discovered_snapshots_inline = process_discovered_snapshots_inline
        self.snapshot_service = SnapshotService(
            self.bus,
            crawl_id=str(crawl.id),
            schedule_snapshot=self.enqueue_snapshot if process_discovered_snapshots_inline else self.leave_snapshot_queued,
        )
        self.archive_result_service = ArchiveResultService(self.bus, process_service=self.process_service)
        self.selected_plugins = selected_plugins
        self.initial_snapshot_ids = snapshot_ids
        self.snapshot_tasks: dict[str, asyncio.Task[None]] = {}
        self.snapshot_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_SNAPSHOTS)
        self.abx_services = None
        self.persona = None
        self.base_config: dict[str, Any] = {}
        self.primary_url = ""
        self._live_stream = None

    def _create_projector_bus(self, *, identifier: str, config_overrides: dict[str, Any]):
        bus = create_bus(name=_bus_name("ArchiveBox", identifier), total_timeout=3600.0)
        process_service = ProcessService(bus)
        MachineService(bus)
        BinaryService(bus)
        TagService(bus)
        ProcessRequestService(bus)
        CrawlService(bus, crawl_id=str(self.crawl.id))
        SnapshotService(
            bus,
            crawl_id=str(self.crawl.id),
            schedule_snapshot=self.enqueue_snapshot if self.process_discovered_snapshots_inline else self.leave_snapshot_queued,
        )
        ArchiveResultService(bus, process_service=process_service)
        abx_services = setup_abx_services(
            bus,
            plugins=self.plugins,
            config_overrides=config_overrides,
            auto_install=True,
            emit_jsonl=False,
        )
        return bus, abx_services

    async def run(self) -> None:
        from asgiref.sync import sync_to_async
        from archivebox.crawls.models import Crawl

        try:
            await sync_to_async(self._prepare, thread_sensitive=True)()
            live_ui = self._create_live_ui()
            with live_ui if live_ui is not None else nullcontext():
                _attach_bus_trace(self.bus)
                self.abx_services = setup_abx_services(
                    self.bus,
                    plugins=self.plugins,
                    config_overrides={
                        **self.base_config,
                        "ABX_RUNTIME": "archivebox",
                    },
                    auto_install=True,
                    emit_jsonl=False,
                )
                snapshot_ids = await sync_to_async(self._initial_snapshot_ids, thread_sensitive=True)()
                if snapshot_ids:
                    root_snapshot_id = snapshot_ids[0]
                    _runner_debug(f"crawl {self.crawl.id} starting crawl setup root_snapshot={root_snapshot_id}")
                    await self._run_crawl_setup(root_snapshot_id)
                    _runner_debug(f"crawl {self.crawl.id} finished crawl setup root_snapshot={root_snapshot_id}")
                    for snapshot_id in snapshot_ids:
                        await self.enqueue_snapshot(snapshot_id)
                    _runner_debug(f"crawl {self.crawl.id} waiting for snapshot tasks count={len(self.snapshot_tasks)}")
                    await self._wait_for_snapshot_tasks()
                    _runner_debug(f"crawl {self.crawl.id} finished waiting for snapshot tasks")
                    _runner_debug(f"crawl {self.crawl.id} starting django crawl.cleanup()")
                    await sync_to_async(self.crawl.cleanup, thread_sensitive=True)()
                    _runner_debug(f"crawl {self.crawl.id} finished django crawl.cleanup()")
                    _runner_debug(f"crawl {self.crawl.id} starting abx crawl cleanup root_snapshot={root_snapshot_id}")
                    await self._run_crawl_cleanup(root_snapshot_id)
                    _runner_debug(f"crawl {self.crawl.id} finished abx crawl cleanup root_snapshot={root_snapshot_id}")
                if self.abx_services is not None:
                    _runner_debug(f"crawl {self.crawl.id} waiting for main bus background monitors")
                    await self.abx_services.process.wait_for_background_monitors()
                    _runner_debug(f"crawl {self.crawl.id} finished waiting for main bus background monitors")
        finally:
            await _stop_bus_trace(self.bus)
            await self.bus.stop()
            if self._live_stream is not None:
                try:
                    self._live_stream.close()
                except Exception:
                    pass
                self._live_stream = None
            await sync_to_async(self._cleanup_persona, thread_sensitive=True)()
            crawl = await sync_to_async(Crawl.objects.get, thread_sensitive=True)(id=self.crawl.id)
            crawl_is_finished = await sync_to_async(crawl.is_finished, thread_sensitive=True)()
            if crawl_is_finished:
                if crawl.status != Crawl.StatusChoices.SEALED:
                    crawl.status = Crawl.StatusChoices.SEALED
                    crawl.retry_at = None
                    await sync_to_async(crawl.save, thread_sensitive=True)(update_fields=["status", "retry_at", "modified_at"])
            else:
                if crawl.status == Crawl.StatusChoices.SEALED:
                    crawl.status = Crawl.StatusChoices.QUEUED
                elif crawl.status != Crawl.StatusChoices.STARTED:
                    crawl.status = Crawl.StatusChoices.STARTED
                crawl.retry_at = crawl.retry_at or timezone.now()
                await sync_to_async(crawl.save, thread_sensitive=True)(update_fields=["status", "retry_at", "modified_at"])

    async def enqueue_snapshot(self, snapshot_id: str) -> None:
        task = self.snapshot_tasks.get(snapshot_id)
        if task is not None and not task.done():
            return
        task = asyncio.create_task(self._run_snapshot(snapshot_id))
        self.snapshot_tasks[snapshot_id] = task

    async def leave_snapshot_queued(self, snapshot_id: str) -> None:
        return None

    async def _wait_for_snapshot_tasks(self) -> None:
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

    def _prepare(self) -> None:
        from archivebox.config.configset import get_config
        from archivebox.machine.models import NetworkInterface, Process

        self.primary_url = self.crawl.get_urls_list()[0] if self.crawl.get_urls_list() else ""
        current_iface = NetworkInterface.current(refresh=True)
        current_process = Process.current()
        if current_process.iface_id != current_iface.id or current_process.machine_id != current_iface.machine_id:
            current_process.iface = current_iface
            current_process.machine = current_iface.machine
            current_process.save(update_fields=["iface", "machine", "modified_at"])
        self.persona = self.crawl.resolve_persona()
        self.base_config = get_config(crawl=self.crawl)
        self.base_config.update(_installed_binary_config_overrides(self.plugins))
        self.base_config["ABX_RUNTIME"] = "archivebox"
        if self.selected_plugins is None:
            self.selected_plugins = _selected_plugins_from_config(self.base_config)
        if self.persona:
            chrome_binary = str(self.base_config.get("CHROME_BINARY") or "")
            self.base_config.update(self.persona.prepare_runtime_for_crawl(self.crawl, chrome_binary=chrome_binary))

    def _cleanup_persona(self) -> None:
        if self.persona:
            self.persona.cleanup_runtime_for_crawl(self.crawl)

    def _create_live_ui(self) -> LiveBusUI | None:
        stdout_is_tty = sys.stdout.isatty()
        stderr_is_tty = sys.stderr.isatty()
        interactive_tty = stdout_is_tty or stderr_is_tty
        if not interactive_tty:
            return None
        stream = sys.stderr if stderr_is_tty else sys.stdout
        if os.path.exists("/dev/tty"):
            try:
                self._live_stream = open("/dev/tty", "w", buffering=1, encoding=getattr(stream, "encoding", None) or "utf-8")
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
            timeout_seconds=int(self.base_config.get("TIMEOUT") or 60),
            ui_console=ui_console,
            interactive_tty=True,
        )
        live_ui.print_intro(
            url=self.primary_url or "crawl",
            output_dir=Path(self.crawl.output_dir),
            plugins_label=plugins_label,
        )
        return live_ui

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
            if snapshot["status"] == "sealed":
                return
            if snapshot["depth"] > 0 and _limit_stop_reason(snapshot["config"]) == "max_size":
                await sync_to_async(self._cancel_snapshot_due_to_limit, thread_sensitive=True)(snapshot_id)
                return
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
            snapshot_bus, snapshot_services = self._create_projector_bus(
                identifier=f"{self.crawl.id}_{snapshot['id']}",
                config_overrides=snapshot["config"],
            )
            try:
                _attach_bus_trace(snapshot_bus)
                _runner_debug(f"snapshot {snapshot_id} starting download()")
                await download(
                    url=snapshot["url"],
                    plugins=self.plugins,
                    output_dir=Path(snapshot["output_dir"]),
                    selected_plugins=self.selected_plugins,
                    config_overrides=snapshot["config"],
                    bus=snapshot_bus,
                    emit_jsonl=False,
                    snapshot=abx_snapshot,
                    skip_crawl_setup=True,
                    skip_crawl_cleanup=True,
                )
                _runner_debug(f"snapshot {snapshot_id} finished download(), waiting for background monitors")
                await snapshot_services.process.wait_for_background_monitors()
                _runner_debug(f"snapshot {snapshot_id} finished waiting for background monitors")
            finally:
                current_task = asyncio.current_task()
                if current_task is not None and self.snapshot_tasks.get(snapshot_id) is current_task:
                    self.snapshot_tasks.pop(snapshot_id, None)
                await _stop_bus_trace(snapshot_bus)
                await snapshot_bus.stop()

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
            "status": snapshot.status,
            "parent_snapshot_id": str(snapshot.parent_snapshot_id) if snapshot.parent_snapshot_id else None,
            "output_dir": str(snapshot.output_dir),
            "config": self._snapshot_config(snapshot),
        }

    def _cancel_snapshot_due_to_limit(self, snapshot_id: str) -> None:
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
    from asgiref.sync import sync_to_async

    from archivebox.config.configset import get_config
    from archivebox.machine.models import Binary

    binary = await sync_to_async(Binary.objects.get, thread_sensitive=True)(id=binary_id)
    plugins = discover_plugins()
    config = get_config()
    config.update(await sync_to_async(_installed_binary_config_overrides, thread_sensitive=True)(plugins))
    config["ABX_RUNTIME"] = "archivebox"
    bus = create_bus(name=_bus_name("ArchiveBox_binary", str(binary.id)), total_timeout=1800.0)
    process_service = ProcessService(bus)
    MachineService(bus)
    BinaryService(bus)
    TagService(bus)
    ProcessRequestService(bus)
    ArchiveResultService(bus, process_service=process_service)
    setup_abx_services(
        bus,
        plugins=plugins,
        config_overrides=config,
        auto_install=True,
        emit_jsonl=False,
    )

    try:
        _attach_bus_trace(bus)
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
        )
    finally:
        await _stop_bus_trace(bus)
        await bus.stop()


def run_binary(binary_id: str) -> None:
    asyncio.run(_run_binary(binary_id))


async def _run_install(plugin_names: list[str] | None = None) -> None:
    from asgiref.sync import sync_to_async

    from archivebox.config.configset import get_config

    plugins = discover_plugins()
    config = get_config()
    config.update(await sync_to_async(_installed_binary_config_overrides, thread_sensitive=True)(plugins))
    config["ABX_RUNTIME"] = "archivebox"
    bus = create_bus(name="ArchiveBox_install", total_timeout=3600.0)
    process_service = ProcessService(bus)
    MachineService(bus)
    BinaryService(bus)
    TagService(bus)
    ProcessRequestService(bus)
    ArchiveResultService(bus, process_service=process_service)
    abx_services = setup_abx_services(
        bus,
        plugins=plugins,
        config_overrides=config,
        auto_install=True,
        emit_jsonl=False,
    )
    live_stream = None

    try:
        selected_plugins = filter_plugins(plugins, list(plugin_names), include_providers=True) if plugin_names else plugins
        if not selected_plugins:
            return
        plugins_label = ", ".join(plugin_names) if plugin_names else f"all ({len(plugins)} available)"
        timeout_seconds = int(config.get("TIMEOUT") or 60)
        stdout_is_tty = sys.stdout.isatty()
        stderr_is_tty = sys.stderr.isatty()
        interactive_tty = stdout_is_tty or stderr_is_tty
        ui_console = None
        live_ui = None

        if interactive_tty:
            stream = sys.stderr if stderr_is_tty else sys.stdout
            if os.path.exists("/dev/tty"):
                try:
                    live_stream = open("/dev/tty", "w", buffering=1, encoding=getattr(stream, "encoding", None) or "utf-8")
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
                _attach_bus_trace(bus)
                results = await abx_install_plugins(
                    plugin_names=plugin_names,
                    plugins=plugins,
                    output_dir=output_dir,
                    config_overrides=config,
                    emit_jsonl=False,
                    bus=bus,
                )
                await abx_services.process.wait_for_background_monitors()
            if live_ui is not None:
                live_ui.print_summary(results, output_dir=output_dir)
    finally:
        await _stop_bus_trace(bus)
        await bus.stop()
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
    running_processes = Process.objects.filter(
        status=Process.StatusChoices.RUNNING,
        process_type__in=[
            Process.TypeChoices.WORKER,
            Process.TypeChoices.HOOK,
            Process.TypeChoices.BINARY,
        ],
    ).only("env")

    for proc in running_processes:
        env = proc.env or {}
        if not isinstance(env, dict):
            continue
        crawl_id = env.get("CRAWL_ID")
        if crawl_id:
            active_crawl_ids.add(str(crawl_id))

    recovered = 0
    now = timezone.now()
    orphaned_crawls = Crawl.objects.filter(
        status=Crawl.StatusChoices.STARTED,
        retry_at__isnull=True,
    ).prefetch_related("snapshot_set")

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
    running_processes = Process.objects.filter(
        status=Process.StatusChoices.RUNNING,
        process_type__in=[
            Process.TypeChoices.WORKER,
            Process.TypeChoices.HOOK,
            Process.TypeChoices.BINARY,
        ],
    ).only("env")

    for proc in running_processes:
        env = proc.env or {}
        if not isinstance(env, dict):
            continue
        snapshot_id = env.get("SNAPSHOT_ID")
        if snapshot_id:
            active_snapshot_ids.add(str(snapshot_id))

    recovered = 0
    now = timezone.now()
    orphaned_snapshots = (
        Snapshot.objects.filter(status=Snapshot.StatusChoices.STARTED, retry_at__isnull=True)
        .select_related("crawl")
        .prefetch_related("archiveresult_set")
    )

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

        if crawl_id is None:
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
            run_crawl(str(queued_crawl.id), process_discovered_snapshots_inline=False)
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
                    process_discovered_snapshots_inline=False,
                )
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

        run_crawl(str(crawl.id), process_discovered_snapshots_inline=False)
