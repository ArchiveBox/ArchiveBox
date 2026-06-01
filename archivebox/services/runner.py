from __future__ import annotations

import asyncio
import contextvars
import json
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from contextlib import nullcontext
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from asgiref.sync import sync_to_async
from django.utils import timezone
from rich.console import Console
from rich.text import Text

from abx_dl.events import (
    BinaryRequestEvent,
    CrawlAbortEvent,
    CrawlCleanupEvent,
    CrawlCompletedEvent,
    CrawlEvent,
    CrawlSetupEvent,
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
from abx_dl.cli import LiveBusUI
from abxbus import BaseEvent
from abxbus.event_bus import EventBus, get_current_event, in_handler_context
from abxbus.event_handler import EventHandlerAbortedError, EventHandlerCancelledError

from archivebox.config.common import ArchiveBoxBaseConfig
from archivebox.core.recovery_util import recover_orchestrator_state
from archivebox.misc.db import run_db_analyze_batch
from archivebox.core.shutdown_util import foreground_shutdown_signals
from archivebox.search.sonic_daemon import register_sonic_daemon_event_handler
from archivebox.workers.models import ACTIVE_STATE_LEASE_SECONDS

from .archive_result_service import ArchiveResultService
from .binary_service import BinaryService
from .crawl_service import CrawlService
from .machine_service import MachineService
from .process_service import ProcessService as PersistedProcessService
from .snapshot_service import SnapshotService, finalize_completed_snapshot
from .tag_service import TagService


def _bus_name(prefix: str, identifier: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in identifier)
    return f"{prefix}_{normalized}"


def _runner_short_id(identifier) -> str:
    return str(identifier).replace("-", "")[-8:]


def _runner_label(value: str, *, reserve: int) -> str:
    width = max(24, shutil.get_terminal_size(fallback=(120, 40)).columns - reserve)
    value = " ".join(str(value or "").split())
    if len(value) <= width:
        return value
    return f"{value[: max(0, width - 3)]}..."


def _runner_console_line(*, crawl=None, crawl_id=None, snapshot=None, status: str = "STARTED") -> None:
    crawl_id = crawl.id if crawl is not None else crawl_id
    line = Text()
    line.append(f"[Crawl#{_runner_short_id(crawl_id)}]", style="cyan bold")
    line.append(" ")
    if snapshot is not None:
        line.append(f"[Snapshot#{_runner_short_id(snapshot.id)}]", style="magenta bold")
        line.append(" ")
    status_styles = {
        "STARTED": "green bold",
        "SEALED": "blue bold",
        "PAUSED": "yellow bold",
    }
    line.append(f"[{status}]", style=status_styles.get(status, "white bold"))
    line.append(" ")
    prefix_width = len(line.plain)
    if snapshot is not None:
        label = snapshot.url
    else:
        label = (getattr(crawl, "label", "") or "").strip()
        if not label:
            label = (getattr(crawl, "urls", "") or "").partition("\n")[0].strip() or str(crawl_id)
    line.append(_runner_label(label, reserve=prefix_width))
    Console(highlight=False).print(line)


def _count_selected_hooks(plugins: dict[str, Plugin], selected_plugins: list[str] | None) -> int:
    selected = filter_plugins(plugins, selected_plugins) if selected_plugins else plugins
    return sum(1 for plugin in selected.values() for hook in plugin.hooks if "CrawlSetup" in hook.name or "Snapshot" in hook.name)


def _normalize_runtime_config(config: ArchiveBoxBaseConfig | Mapping[str, Any] | str | None) -> dict[str, Any]:
    from archivebox.config.common import normalize_runtime_config

    if isinstance(config, ArchiveBoxBaseConfig):
        return config.for_crawl_execution()
    return normalize_runtime_config(config)


def _runner_task_context() -> contextvars.Context:
    context = contextvars.copy_context()
    context.run(EventBus.current_event_context.set, None)
    context.run(EventBus.current_handler_id_context.set, None)
    context.run(EventBus.current_eventbus_context.set, None)
    return context


def _is_external_task_cancelled(error: asyncio.CancelledError) -> bool:
    return not isinstance(error, (EventHandlerAbortedError, EventHandlerCancelledError))


async def _emit_machine_config(
    bus,
    *,
    config: dict[str, Any],
    derived_config: dict[str, Any],
    parent_event=None,
) -> None:
    user_config = _normalize_runtime_config(config)
    derived_machine_config = _normalize_runtime_config(derived_config)
    user_event = MachineEvent(
        config=user_config,
        config_type="user",
    )
    if parent_event is not None:
        user_event.event_parent_id = parent_event.event_id
    await bus.emit(user_event).now()
    if derived_machine_config:
        derived_event = MachineEvent(
            config=derived_machine_config,
            config_type="derived",
        )
        if parent_event is not None:
            derived_event.event_parent_id = parent_event.event_id
        await bus.emit(derived_event).now()


async def _run_event_now(event, timeout: float | None = None):
    await event.now(timeout=timeout)
    await event.wait(timeout=timeout)
    await event.event_results_list()
    return event


def ensure_background_runner(*, allow_under_pytest: bool = False) -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST") and not allow_under_pytest:
        return False

    from archivebox.config import CONSTANTS
    from archivebox.machine.models import Machine, Process
    from archivebox.workers.supervisord_util import get_existing_supervisord_process, get_worker

    supervisor = get_existing_supervisord_process()
    runner_worker = get_worker(supervisor, "worker_runner") if supervisor else None
    if runner_worker and runner_worker.get("statename") in ("STARTING", "RUNNING"):
        return False

    machine = Machine.current()
    running_orchestrators = Process.objects.filter(
        machine=machine,
        status=Process.StatusChoices.RUNNING,
        process_type=Process.TypeChoices.ORCHESTRATOR,
    )
    if any(proc.is_running for proc in running_orchestrators):
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
    def __init__(
        self,
        crawl,
        *,
        snapshot_ids: list[str] | None = None,
        selected_plugins: list[str] | None = None,
        process_discovered_snapshots_inline: bool = True,
        show_progress: bool = True,
        interactive_interrupts: bool = False,
    ):
        self.crawl = crawl
        self.bus = create_bus(name=_bus_name("ArchiveBox", str(crawl.id)), total_timeout=3600.0)
        self.plugins = discover_plugins()
        HookProcessService(self.bus, emit_jsonl=False, interactive_tty=interactive_interrupts)
        register_sonic_daemon_event_handler(self.bus)
        PersistedProcessService(self.bus)
        BinaryService(self.bus)
        TagService(self.bus)
        CrawlService(self.bus, crawl_id=str(crawl.id))
        MachineService(self.bus)
        self.process_discovered_snapshots_inline = process_discovered_snapshots_inline
        self.show_progress = show_progress
        self.interactive_interrupts = interactive_interrupts

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
        self.snapshot_semaphore = asyncio.Semaphore(1)
        self.max_concurrent_snapshots = 1
        self.persona = None
        self.base_config: dict[str, Any] = {}
        self.derived_config: dict[str, Any] = {}
        self.primary_url = ""
        self.crawl_output_dir = ""
        self._live_stream = None
        self.root_crawl_event_id: str | None = None
        self.root_crawl_start_event_id: str | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._skip_wait_until_idle = False
        # This is intentionally a synchronous OS-signal side channel, not bus
        # state. During SIGINT/SIGTERM/SIGHUP, asyncio.run() may already be
        # cancelling tasks and closing the loop, so abxbus cannot be relied on
        # for timely delivery of a final "stop now" event.
        self._signal_abort_requested = False
        self._last_lease_heartbeat_at = 0.0

    def _request_abort_from_signal(self, _sig: signal.Signals) -> None:
        already_requested = self._signal_abort_requested
        self._signal_abort_requested = True
        self._skip_wait_until_idle = True
        # The foreground signal handler runs while the event loop may be in the
        # middle of shutdown. Flip cheap in-memory flags here and let normal
        # finally blocks do cleanup; only cancel the runner task immediately for
        # non-interactive commands or for a second interrupt escalation.
        if (not self.interactive_interrupts or already_requested) and self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()

    async def crawl_is_cancelled(self) -> bool:
        from archivebox.crawls.models import Crawl

        if self._signal_abort_requested:
            return True
        if self.allow_maintenance_on_inactive_crawl:
            # SEALED is the normal terminal state of a finished crawl, not a
            # cancellation signal for maintenance work on its already-sealed
            # snapshots (search backend backfill, fs migration, etc.). When the
            # runner is invoked with explicit snapshot_ids + selected_plugins,
            # treat sealed as completed rather than cancelled so the requested
            # maintenance hooks can actually run.
            return False
        return await Crawl.objects.filter(id=self.crawl.id, status=Crawl.StatusChoices.SEALED).aexists()

    async def crawl_is_paused(self) -> bool:
        from archivebox.crawls.models import Crawl

        crawl = await Crawl.objects.only("status").aget(id=self.crawl.id)
        return crawl.is_paused

    async def watch_for_cancelled_crawl(self, parent_event: BaseEvent, *, poll_interval: float = 1.0) -> None:
        while True:
            await asyncio.sleep(poll_interval)
            if not await self.crawl_is_cancelled():
                continue
            abort_event = parent_event.emit(CrawlAbortEvent())
            await _run_event_now(abort_event, abort_event.event_timeout)
            return

    def runtime_plugins(self) -> dict[str, Plugin]:
        return filter_plugins(self.plugins, self.selected_plugins, include_providers=True) if self.selected_plugins else self.plugins

    @property
    def allow_maintenance_on_inactive_crawl(self) -> bool:
        """Run the requested hooks on a snapshot whose parent crawl is paused or sealed.

        Maintenance entry paths — direct ``snapshot_ids + selected_plugins`` invocations
        for search backend backfill, fs migration, plugin-targeted updates — are
        legitimately allowed to operate on finished/paused crawls. Without this gate,
        ``crawl_is_cancelled`` would treat a SEALED parent as a cancellation signal
        and short-circuit every guard before any hook ran, leaving the queued
        ArchiveResult rows stuck and the orchestrator looping on them.
        """
        return bool(self.initial_snapshot_ids and self.selected_plugins)

    async def run(self) -> None:
        heartbeat = CrawlHeartbeat(
            Path(self.crawl_output_dir),
            runtime="archivebox",
            crawl_id=str(self.crawl.id),
        )
        root_snapshot_id: str | None = None
        bus_destroyed = False
        try:
            first_signal_message = (
                "\n[🛑] Got {signal_name}, aborting the active hook...\n"
                if self.interactive_interrupts
                else "\n[🛑] Got {signal_name}, stopping gracefully...\n"
            )
            # interactive_interrupts is only enabled when this runner belongs
            # to a foreground `archivebox add`. Runners owned by server/update/
            # run should use immediate graceful shutdown instead of the
            # add-specific "abort current hook or continue" flow.
            with foreground_shutdown_signals(
                first_signal_message=first_signal_message,
                on_signal=self._request_abort_from_signal,
                raise_on_first_signal=not self.interactive_interrupts,
            ):
                self._run_task = asyncio.current_task()
                snapshot_ids = await sync_to_async(self.load_run_state, thread_sensitive=True)()
                max_concurrent_snapshots = max(1, int(self.base_config.get("CRAWL_MAX_CONCURRENT_SNAPSHOTS", 1)))
                self.max_concurrent_snapshots = max_concurrent_snapshots
                self.snapshot_semaphore = asyncio.Semaphore(max_concurrent_snapshots)
                live_ui = self._create_live_ui()
                with live_ui if live_ui is not None else nullcontext():
                    try:
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
                            await self.run_crawl(root_snapshot_id, snapshot_ids)
                    finally:
                        self._run_task = None
                        await heartbeat.stop()
                        await self.stop_snapshot_tasks()
                        try:
                            if not self._skip_wait_until_idle:
                                await self.bus.wait_until_idle(timeout=30.0)
                        finally:
                            await self.bus.destroy(clear=False)
                            bus_destroyed = True
        finally:
            if not bus_destroyed:
                self._run_task = None
                await heartbeat.stop()
                await self.stop_snapshot_tasks()
                await self.bus.destroy(clear=False)
            if self._live_stream is not None:
                try:
                    self._live_stream.close()
                except Exception:
                    pass
                self._live_stream = None
            await sync_to_async(self.finalize_run_state, thread_sensitive=True)()

    async def enqueue_snapshot(self, snapshot_id: str, crawl_start_event: CrawlStartEvent | None = None) -> None:
        if await self.crawl_is_cancelled():
            return
        if await self.crawl_is_paused() and not self.allow_maintenance_on_inactive_crawl:
            return
        task = self.snapshot_tasks.get(snapshot_id)
        if task is not None and not task.done():
            return
        current_event = crawl_start_event or get_current_event()
        if isinstance(current_event, CrawlStartEvent):
            task = asyncio.create_task(self.run_snapshot(snapshot_id, current_event), context=_runner_task_context())
        elif in_handler_context():
            return
        else:
            task = asyncio.create_task(self.run_snapshot(snapshot_id), context=_runner_task_context())
        self.snapshot_tasks[snapshot_id] = task

    async def stop_snapshot_tasks(self) -> None:
        if not self.snapshot_tasks:
            return
        tasks = list(self.snapshot_tasks.values())
        if self._signal_abort_requested:
            done = {task for task in tasks if task.done()}
            pending = set(tasks) - done
        else:
            done, pending = await asyncio.wait(tasks, timeout=5.0)
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, *pending, return_exceptions=True)
        self.snapshot_tasks.clear()

    async def wait_for_snapshot_tasks(self) -> None:
        task_errors: list[Exception] = []
        stop_scheduling = False
        while True:
            pending_tasks: list[asyncio.Task[None]] = []
            for snapshot_id, task in list(self.snapshot_tasks.items()):
                if task.done():
                    if self.snapshot_tasks.get(snapshot_id) is task:
                        self.snapshot_tasks.pop(snapshot_id, None)
                    try:
                        task.result()
                    except asyncio.CancelledError as err:
                        if _is_external_task_cancelled(err):
                            raise
                        stop_scheduling = True
                    except Exception as err:
                        task_errors.append(err)
                        stop_scheduling = True
                    continue
                pending_tasks.append(task)
            if not pending_tasks:
                if task_errors:
                    if len(task_errors) == 1:
                        raise task_errors[0]
                    raise ExceptionGroup("One or more snapshot tasks failed", task_errors)
                if stop_scheduling:
                    return
                await self.enqueue_pending_snapshots_from_projection()
                if not self.snapshot_tasks:
                    return
                continue
            await self.heartbeat_active_leases()
            done, _pending = await asyncio.wait(pending_tasks, timeout=10.0, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                continue
            for task in done:
                for snapshot_id, tracked_task in list(self.snapshot_tasks.items()):
                    if tracked_task is task:
                        self.snapshot_tasks.pop(snapshot_id, None)
                        break
                try:
                    task.result()
                except asyncio.CancelledError as err:
                    if _is_external_task_cancelled(err):
                        raise
                    stop_scheduling = True
                except Exception as err:
                    task_errors.append(err)
                    stop_scheduling = True
            if self.snapshot_tasks and (
                await self.crawl_is_cancelled() or (await self.crawl_is_paused() and not self.allow_maintenance_on_inactive_crawl)
            ):
                stop_scheduling = True
            if not stop_scheduling:
                await self.enqueue_pending_snapshots_from_projection()

    async def heartbeat_active_leases(self) -> None:
        if self._run_task is None:
            return
        now_monotonic = time.monotonic()
        if now_monotonic - self._last_lease_heartbeat_at < 10.0:
            return
        self._last_lease_heartbeat_at = now_monotonic
        lease_until = timezone.now() + timedelta(seconds=ACTIVE_STATE_LEASE_SECONDS)
        active_snapshot_ids = [snapshot_id for snapshot_id, task in self.snapshot_tasks.items() if not task.done()]

        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot

        await Crawl.objects.filter(id=self.crawl.id, status=Crawl.StatusChoices.STARTED).aupdate(
            retry_at=lease_until,
            modified_at=timezone.now(),
        )
        if active_snapshot_ids:
            await Snapshot.objects.filter(id__in=active_snapshot_ids, status=Snapshot.StatusChoices.STARTED).aupdate(
                retry_at=lease_until,
                modified_at=timezone.now(),
            )

    async def drain_snapshot_tasks(self) -> None:
        task_errors: list[Exception] = []
        while self.snapshot_tasks:
            done, _pending = await asyncio.wait(list(self.snapshot_tasks.values()), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                for snapshot_id, tracked_task in list(self.snapshot_tasks.items()):
                    if tracked_task is task:
                        self.snapshot_tasks.pop(snapshot_id, None)
                        break
                try:
                    task.result()
                except asyncio.CancelledError as err:
                    if _is_external_task_cancelled(err):
                        raise
                except Exception as err:
                    task_errors.append(err)
        if task_errors:
            if len(task_errors) == 1:
                raise task_errors[0]
            raise ExceptionGroup("One or more snapshot tasks failed", task_errors)

    async def enqueue_pending_snapshots_from_projection(self) -> None:
        from archivebox.core.models import Snapshot
        from archivebox.config.common import get_config

        if not isinstance(get_current_event(), CrawlStartEvent):
            return
        if await self.crawl_is_cancelled():
            return
        if await self.crawl_is_paused() and not self.allow_maintenance_on_inactive_crawl:
            return

        await sync_to_async(self.crawl.refresh_from_db, thread_sensitive=True)()
        config = await sync_to_async(lambda: get_config(crawl=self.crawl, include_machine=False), thread_sensitive=True)()
        self.max_concurrent_snapshots = max(1, int(config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"]))

        active_snapshot_ids = [snapshot_id for snapshot_id, task in self.snapshot_tasks.items() if not task.done()]
        available_slots = max(0, self.max_concurrent_snapshots - len(active_snapshot_ids))
        if available_slots <= 0:
            return
        pending_snapshot_ids = await sync_to_async(
            lambda: list(
                self.crawl.snapshot_set.filter(status__in=[Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED])
                .exclude(id__in=active_snapshot_ids)
                .filter(retry_at__lte=timezone.now())
                .order_by("depth", "created_at")
                .values_list("id", flat=True)[:available_slots],
            ),
            thread_sensitive=True,
        )()
        for snapshot_id in pending_snapshot_ids:
            if snapshot_id not in self.snapshot_tasks:
                await self.enqueue_snapshot(snapshot_id)

    def load_run_state(self) -> list[str]:
        from archivebox.config.common import get_config
        from archivebox.core.models import Snapshot
        from archivebox.hooks import discover_hooks
        from archivebox.machine.models import Machine, NetworkInterface, Process, _sanitize_machine_config

        self.primary_url = self.crawl.get_urls_list()[0] if self.crawl.get_urls_list() else ""
        current_iface = NetworkInterface.current(refresh=True)
        current_process = Process.current()
        if current_process.iface_id != current_iface.id or current_process.machine_id != current_iface.machine_id:
            current_process.iface = current_iface
            current_process.machine = current_iface.machine
            current_process.save(update_fields=["iface", "machine", "modified_at"])
        self.persona = self.crawl.resolve_persona()
        self.base_config = get_config(crawl=self.crawl, include_machine=False)
        self.derived_config = _sanitize_machine_config(Machine.current().config, lib_dir=self.base_config["LIB_DIR"])
        self.crawl_output_dir = str(self.crawl.output_dir)
        self.base_config["ABX_RUNTIME"] = "archivebox"
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
            # Direct snapshot maintenance paths are allowed to name paused
            # snapshots explicitly. The runner still requires selected_plugins
            # later, so this does not restart the crawl lifecycle.
            return [str(snapshot_id) for snapshot_id in self.initial_snapshot_ids]
        if self.crawl.is_paused:
            return []
        pending_snapshots = list(
            self.crawl.snapshot_set.filter(status__in=[Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED])
            .filter(retry_at__lte=timezone.now())
            .order_by("depth", "created_at"),
        )
        if pending_snapshots:
            return [str(snapshot.id) for snapshot in pending_snapshots]
        if self.crawl.snapshot_set.exclude(status__in=[Snapshot.StatusChoices.SEALED, Snapshot.StatusChoices.PAUSED]).exists():
            return []
        created = self.crawl.create_snapshots_from_urls()
        snapshots = created or list(self.crawl.snapshot_set.filter(depth=0).order_by("created_at"))
        return [str(snapshot.id) for snapshot in snapshots]

    def finalize_run_state(self) -> None:
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot

        if self.persona:
            self.persona.cleanup_runtime_for_crawl(self.crawl)
        crawl = Crawl.objects.get(id=self.crawl.id)
        if crawl.status == Crawl.StatusChoices.SEALED:
            return
        if crawl.is_paused:
            return
        if crawl.is_finished():
            if crawl.status != Crawl.StatusChoices.SEALED:
                if crawl.status == Crawl.StatusChoices.STARTED:
                    crawl.sm.seal()
                else:
                    crawl.update_and_requeue(
                        status=Crawl.StatusChoices.SEALED,
                        retry_at=None,
                    )
            return
        active_snapshots = crawl.snapshot_set.filter(
            status__in=[
                Snapshot.StatusChoices.QUEUED,
                Snapshot.StatusChoices.STARTED,
                Snapshot.StatusChoices.PAUSED,
            ],
        )
        next_snapshot_retry = active_snapshots.order_by("retry_at", "created_at").values_list("retry_at", flat=True).first()
        if crawl.status != Crawl.StatusChoices.STARTED:
            crawl.update_and_requeue(
                status=Crawl.StatusChoices.STARTED,
                retry_at=crawl.retry_at or next_snapshot_retry or timezone.now(),
            )
            return
        crawl.update_and_requeue(
            retry_at=crawl.retry_at or next_snapshot_retry or timezone.now(),
        )

    def _create_live_ui(self) -> LiveBusUI | None:
        if not self.show_progress:
            return None
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
        from archivebox.config.common import get_config

        snapshot = Snapshot.objects.select_related("crawl").get(id=snapshot_id)
        config = get_config(crawl=snapshot.crawl, snapshot=snapshot, include_machine=False)
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
            "config": _normalize_runtime_config(config),
            "_snapshot": snapshot,
        }

    async def enqueue_discovered_snapshots_from_outputs(self, snapshot_payload: dict[str, Any]) -> None:
        from archivebox.core.models import Snapshot
        from archivebox.config.common import get_config
        from archivebox.hooks import collect_urls_from_plugins

        await sync_to_async(self.crawl.refresh_from_db, thread_sensitive=True)()
        if self.crawl.is_paused and not self.allow_maintenance_on_inactive_crawl:
            return
        if int(snapshot_payload["depth"]) >= self.crawl.max_depth:
            return

        discovered_urls = await sync_to_async(collect_urls_from_plugins, thread_sensitive=True)(Path(snapshot_payload["output_dir"]))
        if not discovered_urls:
            return

        parent_snapshot = await sync_to_async(
            lambda: Snapshot.objects.select_related("crawl", "crawl__created_by").filter(id=snapshot_payload["id"]).first(),
            thread_sensitive=True,
        )()
        if parent_snapshot is None:
            return
        config = await sync_to_async(
            lambda: get_config(crawl=self.crawl, snapshot=parent_snapshot, include_machine=False),
            thread_sensitive=True,
        )()
        if CrawlLimitState.from_config(config).get_stop_reason() in ("crawl_max_size", "crawl_timeout"):
            return

        await sync_to_async(self.crawl.create_discovered_snapshots, thread_sensitive=True)(
            parent_snapshot,
            discovered_urls,
            depth=parent_snapshot.depth + 1,
        )
        if self.process_discovered_snapshots_inline and isinstance(get_current_event(), CrawlStartEvent):
            await self.enqueue_pending_snapshots_from_projection()

    async def run_crawl(self, root_snapshot_id: str, snapshot_ids: list[str]) -> None:
        snapshot = await sync_to_async(self.load_snapshot_payload, thread_sensitive=True)(root_snapshot_id)
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
        snapshot_hooks = [(plugin, hook) for plugin in plugins.values() for hook in plugin.filter_hooks("Snapshot")]
        max_snapshot_count = max(1, int(config.get("CRAWL_MAX_URLS") or len(snapshot_ids) or 1))
        snapshot_phase_timeout = compute_phase_timeout(snapshot_hooks, config) * max_snapshot_count
        crawl_cleanup_phase_timeout = crawl_setup_phase_timeout
        crawl_lifecycle_timeout = (
            crawl_setup_phase_timeout
            + snapshot_phase_timeout
            + crawl_cleanup_phase_timeout
            + CrawlCompletedEvent.model_fields["event_timeout"].default
            + 30.0
        )
        await _emit_machine_config(self.bus, config=config, derived_config=derived_config)
        install_cancel_watcher: asyncio.Task[None] | None = None
        install_event = self.bus.emit(
            InstallEvent(
                url=snapshot["url"],
                snapshot_id=snapshot["id"],
                output_dir=str(output_dir),
                event_timeout=install_phase_timeout,
                event_handler_slow_timeout=slow_warning_timeout(install_phase_timeout),
            ),
        )

        async def on_archivebox_InstallEvent(event: InstallEvent) -> None:
            nonlocal install_cancel_watcher
            if event.event_id != install_event.event_id:
                return
            install_cancel_watcher = asyncio.create_task(self.watch_for_cancelled_crawl(event))

        on_archivebox_InstallEvent.__name__ = "on_archivebox_InstallEvent__cancel_watcher"
        self.bus.on(InstallEvent, on_archivebox_InstallEvent)
        setup_abx_services(
            self.bus,
            plugins=plugins,
            url=snapshot["url"],
            snapshot=abx_snapshot,
            output_dir=output_dir,
            install_enabled=False,
            crawl_setup_enabled=True,
            crawl_event_enabled=False,
            crawl_start_enabled=False,
            snapshot_cleanup_enabled=False,
            crawl_cleanup_enabled=True,
            crawl_completed_enabled=False,
            crawl_setup_phase_timeout=crawl_setup_phase_timeout,
            snapshot_phase_timeout=crawl_setup_phase_timeout,
            snapshot_cleanup_phase_timeout=crawl_setup_phase_timeout,
            crawl_cleanup_phase_timeout=crawl_setup_phase_timeout,
            persist_derived=False,
            auto_install=True,
            emit_jsonl=False,
            abort_requested=self.crawl_is_cancelled,
            MachineService=None,
            BinaryService=HookBinaryService,
            ProcessService=None,
            ArchiveResultService=None,
            TagService=None,
            SnapshotService=None,
        )
        try:
            await _run_event_now(install_event, install_phase_timeout)
        finally:
            if install_cancel_watcher is not None:
                install_cancel_watcher.cancel()
                await asyncio.gather(install_cancel_watcher, return_exceptions=True)

        async def on_archivebox_CrawlStartEvent(event: CrawlStartEvent) -> None:
            if event.event_id != self.root_crawl_start_event_id:
                return
            for snapshot_id in snapshot_ids:
                if sum(1 for task in self.snapshot_tasks.values() if not task.done()) >= self.max_concurrent_snapshots:
                    break
                if await self.crawl_is_cancelled():
                    break
                if await self.crawl_is_paused() and not self.allow_maintenance_on_inactive_crawl:
                    break
                await self.enqueue_snapshot(snapshot_id)
            await self.wait_for_snapshot_tasks()

        async def on_archivebox_CrawlEvent(event: CrawlEvent) -> None:
            if event.event_id != self.root_crawl_event_id:
                return
            cancel_watcher = asyncio.create_task(self.watch_for_cancelled_crawl(event))
            try:
                try:
                    if not await self.crawl_is_cancelled() and (
                        not await self.crawl_is_paused() or self.allow_maintenance_on_inactive_crawl
                    ):
                        await _run_event_now(
                            event.emit(
                                CrawlSetupEvent(
                                    url=snapshot["url"],
                                    snapshot_id=snapshot["id"],
                                    output_dir=str(output_dir),
                                    event_timeout=crawl_setup_phase_timeout,
                                    event_handler_slow_timeout=slow_warning_timeout(crawl_setup_phase_timeout),
                                ),
                            ),
                            crawl_setup_phase_timeout,
                        )
                    if not await self.crawl_is_cancelled() and (
                        not await self.crawl_is_paused() or self.allow_maintenance_on_inactive_crawl
                    ):
                        crawl_start_event = CrawlStartEvent(
                            url=snapshot["url"],
                            snapshot_id=snapshot["id"],
                            output_dir=str(output_dir),
                            event_timeout=snapshot_phase_timeout,
                            event_handler_timeout=snapshot_phase_timeout + 30.0,
                            event_handler_slow_timeout=slow_warning_timeout(snapshot_phase_timeout),
                        )
                        self.root_crawl_start_event_id = crawl_start_event.event_id
                        await _run_event_now(event.emit(crawl_start_event), None)
                finally:
                    if self.snapshot_tasks:
                        await self.drain_snapshot_tasks()
                    cleanup_event = event.emit(
                        CrawlCleanupEvent(
                            url=snapshot["url"],
                            snapshot_id=snapshot["id"],
                            output_dir=str(output_dir),
                            event_timeout=crawl_setup_phase_timeout,
                            event_handler_slow_timeout=slow_warning_timeout(crawl_setup_phase_timeout),
                        ),
                    )
                    # Normal crawl shutdown drives cleanup synchronously so
                    # ProcessKillEvent handlers get their grace period. During
                    # OS-signal shutdown, asyncio is already cancelling tasks;
                    # keep the child event attached for any remaining bus tick,
                    # but do not call now()/wait() because the bus context may
                    # disappear before delivery and produce noisy shutdown
                    # exceptions instead of useful cleanup.
                    if not self._signal_abort_requested:
                        await _run_event_now(cleanup_event, crawl_setup_phase_timeout)
            finally:
                cancel_watcher.cancel()
                await asyncio.gather(cancel_watcher, return_exceptions=True)
            completed_event = event.emit(
                CrawlCompletedEvent(
                    url=snapshot["url"],
                    snapshot_id=snapshot["id"],
                    output_dir=str(output_dir),
                ),
            )
            # Same signal lifecycle as CrawlCleanupEvent above: completion is a
            # normal bus event unless the interpreter is already unwinding from
            # SIGINT/SIGTERM/SIGHUP, where synchronous bus delivery is no
            # longer a dependable shutdown primitive.
            if not self._signal_abort_requested:
                await _run_event_now(completed_event, CrawlCompletedEvent.model_fields["event_timeout"].default)

        on_archivebox_CrawlStartEvent.__name__ = "on_archivebox_CrawlStartEvent__run_snapshots"
        on_archivebox_CrawlEvent.__name__ = "on_archivebox_CrawlEvent__run_recursive_crawl"
        self.bus.on(CrawlStartEvent, on_archivebox_CrawlStartEvent)
        self.bus.on(CrawlEvent, on_archivebox_CrawlEvent)

        crawl_event = CrawlEvent(
            url=snapshot["url"],
            snapshot_id=snapshot["id"],
            output_dir=str(output_dir),
            event_timeout=crawl_lifecycle_timeout,
            event_handler_timeout=crawl_lifecycle_timeout + 30.0,
            event_handler_slow_timeout=slow_warning_timeout(crawl_lifecycle_timeout),
        )
        self.root_crawl_event_id = crawl_event.event_id
        await _run_event_now(self.bus.emit(crawl_event), None)
        if await self.crawl_is_cancelled():
            self._skip_wait_until_idle = True
            return
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
            await completed_process.wait(timeout=crawl_setup_phase_timeout)
            await completed_process.event_results_list()
            if completed_process.status == "failed":
                raise RuntimeError(f"Crawl setup hook {plugin.name}:{hook.name} failed")

    async def run_snapshot(self, snapshot_id: str, crawl_start_event: CrawlStartEvent | None = None) -> None:
        async with self.snapshot_semaphore:
            crawl_start_event = crawl_start_event or get_current_event()
            if not isinstance(crawl_start_event, CrawlStartEvent):
                raise RuntimeError("Snapshot events must be emitted from a CrawlStartEvent handler")
            snapshot = await sync_to_async(self.load_snapshot_payload, thread_sensitive=True)(snapshot_id)
            if snapshot["status"] == "sealed" and not self.selected_plugins:
                await sync_to_async(run_snapshot_maintenance, thread_sensitive=True)(snapshot_id)
                return
            snapshot_selected_plugins = self.selected_plugins
            if snapshot["status"] == "started":
                _reset_count, running_count = await sync_to_async(snapshot["_snapshot"].reset_abandoned_results, thread_sensitive=True)()
                if running_count:
                    await sync_to_async(
                        lambda: snapshot["_snapshot"].update_and_requeue(
                            retry_at=timezone.now() + timedelta(seconds=ACTIVE_STATE_LEASE_SECONDS),
                        ),
                        thread_sensitive=True,
                    )()
                    return
                snapshot_selected_plugins = snapshot_selected_plugins or await sync_to_async(
                    queued_plugins_for_snapshot,
                    thread_sensitive=True,
                )(snapshot["id"])
            if snapshot["depth"] > 0 and CrawlLimitState.from_config(snapshot["config"]).get_stop_reason() in (
                "crawl_max_size",
                "crawl_timeout",
            ):
                await sync_to_async(self.seal_snapshot_due_to_limit, thread_sensitive=True)(snapshot_id)
                return
            config = _normalize_runtime_config(snapshot["config"])
            derived_config = _normalize_runtime_config(self.derived_config)
            output_dir = Path(snapshot["output_dir"])
            plugins = (
                filter_plugins(self.plugins, snapshot_selected_plugins, include_providers=True)
                if snapshot_selected_plugins
                else self.plugins
            )
            abx_snapshot = AbxSnapshot(
                id=snapshot["id"],
                url=snapshot["url"],
                depth=int(snapshot["depth"]),
                crawl_id=str(self.crawl.id),
            )
            snapshot_hooks = [(plugin, hook) for plugin in plugins.values() for hook in plugin.filter_hooks("Snapshot")]
            snapshot_phase_timeout = compute_phase_timeout(snapshot_hooks, config)
            await _emit_machine_config(self.bus, config=config, derived_config=derived_config, parent_event=crawl_start_event)
            snapshot_service = HookSnapshotService(
                self.bus,
                url=snapshot["url"],
                snapshot=abx_snapshot,
                output_dir=output_dir,
                plugins=plugins,
                snapshot_phase_timeout=snapshot_phase_timeout,
                snapshot_cleanup_enabled=True,
                snapshot_cleanup_phase_timeout=snapshot_phase_timeout,
                abort_requested=self.crawl_is_cancelled,
            )
            try:
                snapshot_event = SnapshotEvent(
                    url=snapshot["url"],
                    snapshot_id=snapshot["id"],
                    output_dir=str(output_dir),
                    depth=int(snapshot["depth"]),
                    event_timeout=snapshot_phase_timeout,
                    event_handler_slow_timeout=slow_warning_timeout(snapshot_phase_timeout),
                )
                snapshot_event.event_parent_id = crawl_start_event.event_id
                emitted_snapshot_event = self.bus.emit(snapshot_event)
                await _run_event_now(emitted_snapshot_event, snapshot_phase_timeout)
                completed_snapshot = await self.bus.find(
                    SnapshotCompletedEvent,
                    child_of=emitted_snapshot_event,
                    past=True,
                    future=snapshot_phase_timeout,
                )
                if completed_snapshot is None:
                    raise RuntimeError(f"Snapshot {snapshot_id} did not complete")
                await completed_snapshot.wait(timeout=snapshot_phase_timeout)
                await completed_snapshot.event_results_list()
                # SnapshotCompletedEvent is the normal projection path, but the
                # runner is the scheduler owner. Finalize idempotently here too
                # so a completed snapshot cannot remain STARTED if the event was
                # observed before its DB projector advanced the state machine.
                await sync_to_async(finalize_completed_snapshot, thread_sensitive=True)(snapshot_id)
                if snapshot["status"] == "sealed":
                    await sync_to_async(run_snapshot_maintenance, thread_sensitive=True)(snapshot_id)
                    return
                await self.enqueue_discovered_snapshots_from_outputs(snapshot)
                await sync_to_async(
                    lambda: (
                        self.crawl.sm.seal()
                        if self.crawl.status == self.crawl.StatusChoices.STARTED
                        and not self.crawl.snapshot_set.filter(
                            status__in=[
                                self.crawl.snapshot_set.model.StatusChoices.QUEUED,
                                self.crawl.snapshot_set.model.StatusChoices.STARTED,
                                self.crawl.snapshot_set.model.StatusChoices.PAUSED,
                            ],
                        ).exists()
                        else None
                    ),
                    thread_sensitive=True,
                )()
            finally:
                snapshot_service.close()

    def seal_snapshot_due_to_limit(self, snapshot_id: str) -> None:
        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.filter(id=snapshot_id).first()
        if snapshot is None or snapshot.status == Snapshot.StatusChoices.SEALED:
            return
        if snapshot.status == Snapshot.StatusChoices.STARTED:
            snapshot.sm.seal()
            return
        snapshot.update_and_requeue(
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )


def run_crawl(
    crawl_id: str,
    *,
    snapshot_ids: list[str] | None = None,
    selected_plugins: list[str] | None = None,
    process_discovered_snapshots_inline: bool = True,
    show_progress: bool = True,
    interactive_interrupts: bool = False,
) -> None:
    from archivebox.crawls.models import Crawl
    from django.db import close_old_connections

    def run_in_current_thread() -> None:
        close_old_connections()
        try:
            crawl = Crawl.objects.get(id=crawl_id)
            asyncio.run(
                CrawlRunner(
                    crawl,
                    snapshot_ids=snapshot_ids,
                    selected_plugins=selected_plugins,
                    process_discovered_snapshots_inline=process_discovered_snapshots_inline,
                    show_progress=show_progress,
                    interactive_interrupts=interactive_interrupts,
                ).run(),
            )
        finally:
            close_old_connections()

    if threading.current_thread() is threading.main_thread():
        run_in_current_thread()
        return

    errors: list[BaseException] = []

    def run_in_worker_thread() -> None:
        try:
            run_in_current_thread()
        except BaseException as err:
            errors.append(err)

    worker = threading.Thread(target=run_in_worker_thread, name=f"archivebox-crawl-{crawl_id}")
    worker.start()
    worker.join()
    if errors:
        raise errors[0]


async def _run_binary(binary_id: str) -> None:
    from archivebox.config.common import get_config
    from archivebox.machine.models import Binary, Machine, _sanitize_machine_config

    binary = await Binary.objects.aget(id=binary_id)
    plugins = discover_plugins()
    config = get_config(include_machine=False)
    machine = await sync_to_async(Machine.current, thread_sensitive=True)()
    derived_config = _normalize_runtime_config(_sanitize_machine_config(machine.config, lib_dir=config["LIB_DIR"]))
    config["ABX_RUNTIME"] = "archivebox"
    config = _normalize_runtime_config(config)
    bus = create_bus(name=_bus_name("ArchiveBox_binary", str(binary.id)), total_timeout=1800.0)
    process_service = PersistedProcessService(bus)
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
        await process_service.flush_completed()


def run_binary(binary_id: str) -> None:
    asyncio.run(_run_binary(binary_id))


@lru_cache(maxsize=1)
def _snapshot_hook_names_by_plugin() -> dict[str, frozenset[str]]:
    return {plugin.name: frozenset(hook.name for hook in plugin.filter_hooks("Snapshot")) for plugin in discover_plugins().values()}


def queued_plugins_for_snapshot(snapshot_id: str) -> list[str] | None:
    from archivebox.core.models import ArchiveResult

    queued_results = list(
        ArchiveResult.objects.filter(
            snapshot_id=snapshot_id,
            status=ArchiveResult.StatusChoices.QUEUED,
        )
        .exclude(plugin="")
        .only("id", "plugin", "hook_name"),
    )
    hooks_by_plugin = _snapshot_hook_names_by_plugin()
    obsolete_result_ids = [
        result.id
        for result in queued_results
        if result.hook_name and result.hook_name not in hooks_by_plugin.get(result.plugin, frozenset())
    ]
    if obsolete_result_ids:
        # Hook names are the scheduler identity for ArchiveResults. If an old
        # queued row names a hook that the current plugin model cannot run, hard
        # fail only that row so the scheduler drains without hiding stale/broken
        # plugin state as an intentional skip.
        ArchiveResult.objects.filter(
            id__in=obsolete_result_ids,
            status=ArchiveResult.StatusChoices.QUEUED,
        ).update(
            status=ArchiveResult.StatusChoices.FAILED,
            output_str="Hook no longer exists in the current plugin set.",
            modified_at=timezone.now(),
        )

    queued_plugins = sorted({result.plugin for result in queued_results if result.id not in obsolete_result_ids})
    if queued_plugins:
        return queued_plugins
    return None


def run_snapshot_maintenance(snapshot_id: str) -> bool:
    from archivebox.core.models import ArchiveResult, Snapshot

    snapshot = Snapshot.objects.filter(id=snapshot_id).first()
    if snapshot is None:
        return False

    has_queued_results = snapshot.archiveresult_set.filter(status=ArchiveResult.StatusChoices.QUEUED).exists()
    # retry_at is the scheduler signal for both lifecycle work and targeted
    # maintenance. Filesystem migration/json rewriting is independent from
    # queued ArchiveResult rows, so run it whenever this helper is called.
    # The only thing queued rows change is the next scheduler value:
    # - no queued rows left: clear retry_at because maintenance is done
    # - queued rows remain: leave the Snapshot due so the sealed/paused runner
    #   branch can process those targeted plugin rows on the next tick
    # This avoids reopening final/paused snapshots while also avoiding stranded
    # queued ArchiveResults that have no independent scheduler.
    snapshot.retry_at = timezone.now() if has_queued_results else None
    snapshot.save(update_fields=["retry_at", "modified_at"])
    snapshot.write_index_jsonl()
    snapshot.write_json_details()
    snapshot.write_html_details()
    return True


def run_due_crawl(crawl, *, lock_seconds: int, interactive_interrupts: bool = False) -> bool:
    try:
        crawl.refresh_from_db(fields=["status", "retry_at", "modified_at"])
    except type(crawl).DoesNotExist:
        return False

    if crawl.is_paused:
        _runner_console_line(crawl=crawl, status="PAUSED")
        return True
    if crawl.status in (crawl.StatusChoices.QUEUED, crawl.StatusChoices.STARTED):
        from archivebox.core.models import Snapshot

        now = timezone.now()
        snapshot_count = crawl.snapshot_set.count()
        due_active_snapshots = crawl.snapshot_set.filter(
            status__in=[Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED],
            retry_at__lte=now,
        ).exists()
        if snapshot_count and due_active_snapshots:
            # Child Snapshot rows own active work. Do not rewrite the parent
            # row unless it is still the same STARTED row we selected; this
            # avoids hot-looping on the parent while child work is ready without
            # resurrecting a user cancellation that sealed the crawl after
            # selection.
            crawl.safe_update(
                {
                    "status": crawl.StatusChoices.STARTED,
                    "retry_at": now + timedelta(seconds=ACTIVE_STATE_LEASE_SECONDS),
                    "modified_at": now,
                },
                refresh=False,
                extra_filter={"status": crawl.StatusChoices.STARTED},
            )
            return True
        if snapshot_count and not due_active_snapshots:
            if crawl.is_finished():
                if not crawl.claim_processing_lock(lock_seconds=lock_seconds):
                    return False
                crawl.refresh_from_db()
                crawl.sm.tick()
                return True

            # retry_at is the only queue/ownership signal the runner sees.
            # Clearing it on an unfinished crawl hides the row forever, so keep
            # future snapshots scheduled and repair NULL queued child locks here.
            unlocked_children = crawl.snapshot_set.filter(
                status=Snapshot.StatusChoices.QUEUED,
                retry_at__isnull=True,
            ).update(
                retry_at=now,
                modified_at=now,
            )
            if unlocked_children:
                crawl.update_and_requeue(status=crawl.StatusChoices.STARTED, retry_at=now)
                return True

            next_snapshot_retry = (
                crawl.snapshot_set.filter(
                    status__in=[
                        Snapshot.StatusChoices.QUEUED,
                        Snapshot.StatusChoices.STARTED,
                        Snapshot.StatusChoices.PAUSED,
                    ],
                    retry_at__gt=now,
                )
                .order_by("retry_at", "created_at")
                .values_list("retry_at", flat=True)
                .first()
            )
            crawl.update_and_requeue(
                status=crawl.StatusChoices.STARTED,
                retry_at=next_snapshot_retry or now + timedelta(seconds=10),
            )
            return True
        if not crawl.claim_processing_lock(lock_seconds=lock_seconds):
            return False
        crawl.refresh_from_db()
        if crawl.status == crawl.StatusChoices.STARTED and crawl.is_finished():
            crawl.sm.tick()
            return True
        _runner_console_line(crawl=crawl)
        run_crawl(str(crawl.id), process_discovered_snapshots_inline=True, interactive_interrupts=interactive_interrupts)
        return True

    if crawl.status == crawl.StatusChoices.SEALED:
        if not type(crawl).claim_for_worker(crawl, lock_seconds=lock_seconds):
            return False
        _runner_console_line(crawl=crawl, status="SEALED")
        crawl.cleanup()
        crawl.update_and_requeue(retry_at=None)
        return True

    crawl.update_and_requeue(retry_at=None)
    return True


def run_due_snapshot(snapshot, *, lock_seconds: int, interactive_interrupts: bool = False, runtime_config=None) -> bool:
    from archivebox.core.models import Snapshot

    try:
        snapshot = Snapshot.objects.get(pk=snapshot.pk)
    except Snapshot.DoesNotExist:
        return False
    if runtime_config is not None:
        snapshot._runtime_config = runtime_config
    parent_reconciled = snapshot.reconcile_parent_lifecycle(lock_seconds=lock_seconds)
    if parent_reconciled is not None:
        return parent_reconciled

    if snapshot.is_paused:
        selected_plugins = queued_plugins_for_snapshot(str(snapshot.id))
        if snapshot.fs_migration_needed and Snapshot.claim_for_worker(snapshot, lock_seconds=lock_seconds):
            _runner_console_line(crawl_id=snapshot.crawl_id, snapshot=snapshot)
            run_snapshot_maintenance(str(snapshot.id))
            if not selected_plugins:
                # No targeted plugin rows remain, so put paused snapshots back
                # behind the indefinite retry_at marker. If queued plugin rows
                # do remain, run_snapshot_maintenance kept retry_at due so the
                # next tick can process them and the finally block below will
                # restore the paused marker after that targeted work completes.
                snapshot.restore_paused_scheduler_marker()
            return True
        if not selected_plugins:
            # Paused is a real lifecycle state; retry_at=MAX is only the
            # orchestrator selection marker. If a direct maintenance/update
            # command bumps retry_at on a paused snapshot but there are no
            # targeted ArchiveResult rows to run, restore the scheduler marker
            # without changing status.
            snapshot.restore_paused_scheduler_marker()
            return True
        if not Snapshot.claim_for_worker(snapshot, lock_seconds=lock_seconds):
            return False
        try:
            _runner_console_line(crawl_id=snapshot.crawl_id, snapshot=snapshot)
            # Explicit maintenance, e.g. `archivebox update --index-only`, may
            # need to run search/index hooks for a paused snapshot. That should
            # not resume the crawl or make unrelated queued work runnable, so
            # selected_plugins is required and the paused state is restored in
            # the finally block below.
            run_crawl(
                str(snapshot.crawl_id),
                snapshot_ids=[str(snapshot.id)],
                selected_plugins=selected_plugins,
                process_discovered_snapshots_inline=True,
                interactive_interrupts=interactive_interrupts,
            )
        finally:
            # Targeted plugin rows can complete while the Snapshot remains
            # paused. Put retry_at back at MAX so the orchestrator leaves the
            # paused lifecycle alone until an explicit resume transition.
            snapshot.restore_paused_scheduler_marker()
        return True
    if snapshot.status == Snapshot.StatusChoices.SEALED:
        if not Snapshot.claim_for_worker(snapshot, lock_seconds=lock_seconds):
            return False
        snapshot.refresh_from_db()
        snapshot.finalize_completed_upload_results()
        if snapshot.fs_migration_needed:
            # Final snapshots can still need maintenance after an old data-dir
            # migration. Run the filesystem/json save path before queued search
            # backfill rows so both maintenance streams stay ordered without
            # changing Snapshot.status away from SEALED.
            _runner_console_line(crawl_id=snapshot.crawl_id, snapshot=snapshot)
            return run_snapshot_maintenance(str(snapshot.id))
        selected_plugins = queued_plugins_for_snapshot(str(snapshot.id))
        if selected_plugins:
            _runner_console_line(crawl_id=snapshot.crawl_id, snapshot=snapshot)
            run_crawl(
                str(snapshot.crawl_id),
                snapshot_ids=[str(snapshot.id)],
                selected_plugins=selected_plugins,
                process_discovered_snapshots_inline=True,
                interactive_interrupts=interactive_interrupts,
            )
            return True
        return run_snapshot_maintenance(str(snapshot.id))

    if snapshot.status == Snapshot.StatusChoices.STARTED:
        _reset_count, running_count = snapshot.reset_abandoned_results()
        if running_count:
            snapshot.update_and_requeue(retry_at=timezone.now() + timedelta(seconds=ACTIVE_STATE_LEASE_SECONDS))
            return True

    if not snapshot.claim_processing_lock(lock_seconds=lock_seconds):
        return False
    snapshot.refresh_from_db()
    if snapshot.status == Snapshot.StatusChoices.QUEUED:
        if snapshot.archiveresult_set.exists() and snapshot.is_finished_processing():
            snapshot.sm.tick()
            snapshot.refresh_from_db()
            if snapshot.status == Snapshot.StatusChoices.SEALED:
                _runner_console_line(crawl_id=snapshot.crawl_id, snapshot=snapshot, status="SEALED")
                return True
        # The runner owns queued Snapshot setup. Create missing enabled hook
        # rows before ticking so maintenance-only final rows, e.g. search
        # backfill on a paused snapshot, cannot make queued -> sealed skip the
        # real extraction work after resume.
        snapshot.create_pending_archiveresults()
        snapshot.sm.tick()
        snapshot.refresh_from_db()
        if snapshot.status == Snapshot.StatusChoices.SEALED:
            _runner_console_line(crawl_id=snapshot.crawl_id, snapshot=snapshot, status="SEALED")
            return True
    if snapshot.status == Snapshot.StatusChoices.STARTED and snapshot.archiveresult_set.exists() and snapshot.is_finished_processing():
        snapshot.sm.tick()
        snapshot.refresh_from_db()
        if snapshot.status == Snapshot.StatusChoices.SEALED:
            _runner_console_line(crawl_id=snapshot.crawl_id, snapshot=snapshot, status="SEALED")
            return True
    _runner_console_line(crawl_id=snapshot.crawl_id, snapshot=snapshot)
    run_crawl(
        str(snapshot.crawl_id),
        snapshot_ids=[str(snapshot.id)],
        selected_plugins=queued_plugins_for_snapshot(str(snapshot.id)),
        process_discovered_snapshots_inline=True,
        interactive_interrupts=interactive_interrupts,
    )
    return True


def run_due_binary(binary, *, lock_seconds: int) -> bool:
    binary_name = str(binary.name or "")
    binary_path = Path(binary_name).expanduser()
    if (binary_path.is_absolute() or binary_name.startswith("~")) and not binary_path.exists():
        binary.retry_at = None
        binary.save(update_fields=["retry_at", "modified_at"])
        return True
    if not binary.claim_processing_lock(lock_seconds=lock_seconds):
        return False
    run_binary(str(binary.id))
    return True


async def _run_install(plugin_names: list[str] | None = None) -> None:
    from archivebox.config.common import get_config
    from archivebox.machine.models import Machine, _sanitize_machine_config

    plugins = discover_plugins()
    config = get_config(include_machine=False)
    machine = await sync_to_async(Machine.current, thread_sensitive=True)()
    derived_config = _normalize_runtime_config(_sanitize_machine_config(machine.config, lib_dir=config["LIB_DIR"]))
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
    bus_destroyed = False

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
                try:
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
                finally:
                    try:
                        await bus.wait_until_idle()
                    finally:
                        await bus.destroy(clear=False)
                        bus_destroyed = True
            if live_ui is not None:
                live_ui.print_summary(output_dir=output_dir)
    finally:
        if not bus_destroyed:
            await bus.destroy(clear=False)
        try:
            if live_stream is not None:
                live_stream.close()
        except Exception:
            pass


def run_install(*, plugin_names: list[str] | None = None) -> None:
    asyncio.run(_run_install(plugin_names=plugin_names))


def _first_due_id(queryset):
    return queryset.order_by("retry_at", "created_at").values_list("id", flat=True).first()


def _run_due_crawl_status(status: str, *, crawl_id: str | None, lock_seconds: int, interactive_interrupts: bool) -> bool:
    from archivebox.crawls.models import Crawl

    due_crawls = Crawl.objects.filter(
        retry_at__lte=timezone.now(),
        status=status,
    )
    if crawl_id:
        due_crawls = due_crawls.filter(id=crawl_id)
    due_crawl_id = _first_due_id(due_crawls)
    if due_crawl_id is None:
        return False
    due_crawl = Crawl.objects.filter(id=due_crawl_id).first()
    if due_crawl is None:
        return True
    run_due_crawl(
        due_crawl,
        lock_seconds=lock_seconds,
        interactive_interrupts=interactive_interrupts,
    )
    return True


def _run_due_snapshot_query(queryset, *, lock_seconds: int, interactive_interrupts: bool, runtime_config) -> bool:
    due_snapshot_id = _first_due_id(queryset)
    return _run_due_snapshot_id(
        due_snapshot_id,
        lock_seconds=lock_seconds,
        interactive_interrupts=interactive_interrupts,
        runtime_config=runtime_config,
    )


def _run_due_snapshot_id(snapshot_id, *, lock_seconds: int, interactive_interrupts: bool, runtime_config) -> bool:
    from archivebox.core.models import Snapshot

    due_snapshot_id = snapshot_id
    if due_snapshot_id is None:
        return False
    due_snapshot = Snapshot.objects.filter(id=due_snapshot_id).first()
    if due_snapshot is None:
        return True
    run_due_snapshot(
        due_snapshot,
        lock_seconds=lock_seconds,
        interactive_interrupts=interactive_interrupts,
        runtime_config=runtime_config,
    )
    return True


def _run_due_queued_download_result(
    download_plugin_names: frozenset[str],
    *,
    crawl_id: str | None,
    lock_seconds: int,
    interactive_interrupts: bool,
    runtime_config,
) -> bool:
    from archivebox.core.models import ArchiveResult, Snapshot

    if not download_plugin_names:
        return False
    queued_results = ArchiveResult.objects.filter(
        status=ArchiveResult.StatusChoices.QUEUED,
        plugin__in=download_plugin_names,
        snapshot__status=Snapshot.StatusChoices.SEALED,
        snapshot__retry_at__lte=timezone.now(),
    )
    if crawl_id:
        queued_results = queued_results.filter(snapshot__crawl_id=crawl_id)
    due_snapshot_id = queued_results.order_by("snapshot__retry_at", "snapshot__created_at").values_list("snapshot_id", flat=True).first()
    return _run_due_snapshot_id(
        due_snapshot_id,
        lock_seconds=lock_seconds,
        interactive_interrupts=interactive_interrupts,
        runtime_config=runtime_config,
    )


def _run_due_binary() -> bool:
    from archivebox.machine.models import Binary

    due_binary_id = (
        Binary.objects.filter(retry_at__lte=timezone.now())
        .exclude(status=Binary.StatusChoices.INSTALLED)
        .order_by("retry_at", "created_at")
        .values_list("id", flat=True)
        .first()
    )
    if due_binary_id is None:
        return False
    due_binary = Binary.objects.filter(id=due_binary_id).first()
    if due_binary is None:
        return True
    run_due_binary(due_binary, lock_seconds=60)
    return True


def run_pending_crawls(
    *,
    daemon: bool = False,
    crawl_id: str | None = None,
    maintenance_only: bool = False,
    interactive_interrupts: bool = False,
) -> int:
    from archivebox.config.common import get_config
    from archivebox.crawls.models import Crawl, CrawlSchedule
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.hooks import discover_plugin_configs
    from archivebox.machine.models import Process

    crawl_claim_lock_seconds = 10
    runtime_config = get_config()
    plugin_configs = discover_plugin_configs()
    download_plugin_names = frozenset(
        plugin_name
        for plugin_name, plugin_config in plugin_configs.items()
        if plugin_config.get("output_mimetypes") and not plugin_name.startswith("search_backend_")
    )
    last_recovery_at = 0.0
    last_retention_at = 0.0
    last_analyze_at = 0.0
    analyze_queue: list[str] | None = None
    analyze_sweep_started_at = 0.0
    orchestrator_started_at = time.monotonic()
    while True:
        now_monotonic = time.monotonic()
        if now_monotonic - last_retention_at >= (60.0 if daemon else 1.0):
            for model in (ArchiveResult, Snapshot, Crawl, Process):
                # The runner hot path must only touch indexed scheduler/retention
                # columns before claiming work. delete_at is hydrated when rows
                # are saved, while missing_delete_at_candidates() may inspect JSON
                # config across large tables and can stall worker startup.
                model.delete_expired(batch_size=100, backfill_missing=False)
            last_retention_at = now_monotonic

        if daemon and crawl_id is None:
            now = timezone.now()
            for schedule in CrawlSchedule.objects.filter(is_enabled=True).select_related("template", "template__created_by"):
                if schedule.is_due(now):
                    schedule.enqueue(queued_at=now)

        # Final-state download rows are always first: they have no parent crawl
        # scheduler of their own, and leaving them behind makes the global
        # counters report stale queued work while new crawls continue.
        if _run_due_queued_download_result(
            download_plugin_names,
            crawl_id=crawl_id,
            lock_seconds=60,
            interactive_interrupts=interactive_interrupts,
            runtime_config=runtime_config,
        ):
            continue

        # Other final-state snapshot work comes next: search backfills,
        # filesystem/json maintenance, and upload finalization should drain
        # before starting or resuming regular crawl work.
        sealed_snapshots = Snapshot.objects.filter(
            retry_at__lte=timezone.now(),
            status=Snapshot.StatusChoices.SEALED,
        )
        if crawl_id:
            sealed_snapshots = sealed_snapshots.filter(crawl_id=crawl_id)
        if _run_due_snapshot_query(
            sealed_snapshots,
            lock_seconds=60,
            interactive_interrupts=interactive_interrupts,
            runtime_config=runtime_config,
        ):
            continue

        if not maintenance_only:
            active_snapshots = Snapshot.objects.filter(
                retry_at__lte=timezone.now(),
                crawl__status__in=[Crawl.StatusChoices.QUEUED, Crawl.StatusChoices.STARTED],
                status__in=[Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED],
            )
            if crawl_id:
                active_snapshots = active_snapshots.filter(crawl_id=crawl_id)
            if _run_due_snapshot_query(
                active_snapshots,
                lock_seconds=60,
                interactive_interrupts=interactive_interrupts,
                runtime_config=runtime_config,
            ):
                continue

        if not maintenance_only:
            if _run_due_crawl_status(
                Crawl.StatusChoices.QUEUED,
                crawl_id=crawl_id,
                lock_seconds=crawl_claim_lock_seconds,
                interactive_interrupts=interactive_interrupts,
            ):
                continue

        if not maintenance_only:
            if _run_due_crawl_status(
                Crawl.StatusChoices.STARTED,
                crawl_id=crawl_id,
                lock_seconds=crawl_claim_lock_seconds,
                interactive_interrupts=interactive_interrupts,
            ):
                continue

        if not maintenance_only:
            # Canceled-crawl child sealing is important cleanup, but it must
            # not starve live crawl work when a large bulk cancel leaves many
            # children due at once.
            cancelling_snapshots = Snapshot.objects.filter(
                retry_at__lte=timezone.now(),
                crawl__status=Crawl.StatusChoices.SEALED,
                status=Snapshot.StatusChoices.STARTED,
            )
            if crawl_id:
                cancelling_snapshots = cancelling_snapshots.filter(crawl_id=crawl_id)
            if _run_due_snapshot_query(
                cancelling_snapshots,
                lock_seconds=60,
                interactive_interrupts=interactive_interrupts,
                runtime_config=runtime_config,
            ):
                continue

        if not maintenance_only:
            pausing_snapshots = Snapshot.objects.filter(
                retry_at__lte=timezone.now(),
                crawl__status=Crawl.StatusChoices.PAUSED,
                status__in=[
                    Snapshot.StatusChoices.QUEUED,
                    Snapshot.StatusChoices.STARTED,
                ],
            )
            if crawl_id:
                pausing_snapshots = pausing_snapshots.filter(crawl_id=crawl_id)
            if _run_due_snapshot_query(
                pausing_snapshots,
                lock_seconds=60,
                interactive_interrupts=interactive_interrupts,
                runtime_config=runtime_config,
            ):
                continue

        # Final fallback uses only the retry_at scheduler index and selects an
        # id first. The active/paused/sealed parent-specific branches above get
        # first priority, so this stays broad without hydrating wide rows or
        # forcing SQLite into a slow status/join plan.
        due_snapshots = Snapshot.objects.filter(retry_at__lte=timezone.now())
        if maintenance_only:
            due_snapshots = due_snapshots.filter(status=Snapshot.StatusChoices.PAUSED)
        if crawl_id:
            due_snapshots = due_snapshots.filter(crawl_id=crawl_id)
        if _run_due_snapshot_query(
            due_snapshots,
            lock_seconds=60,
            interactive_interrupts=interactive_interrupts,
            runtime_config=runtime_config,
        ):
            continue

        if not maintenance_only:
            if _run_due_crawl_status(
                Crawl.StatusChoices.SEALED,
                crawl_id=crawl_id,
                lock_seconds=crawl_claim_lock_seconds,
                interactive_interrupts=interactive_interrupts,
            ):
                continue

        if crawl_id is None and not maintenance_only:
            if _run_due_binary():
                continue

        if daemon:
            now_monotonic = time.monotonic()
            if now_monotonic - last_recovery_at >= 30.0:
                recover_orchestrator_state()
                last_recovery_at = now_monotonic
            # SQLite query plans degrade as the snapshot/archiveresult tables grow
            # past their last ANALYZE — stale stats make the optimizer start large
            # joins from auth_user/crawl instead of using the url index, blowing the
            # snapshot detail page out to ~500ms. Refresh stats at most once per
            # 24hr while the queue is idle, and only after the orchestrator has
            # been alive for at least an hour so short server boots / one-off work
            # never pay the cost. The sweep is batched one table per idle tick;
            # individual table ANALYZE statements abort after 2min (progress
            # handler) and the whole sweep is hard-capped at 5min so a
            # pathological table cannot wedge maintenance forever. Any failure
            # inside the maintenance hook is swallowed — orchestrator must never
            # be taken down by stats refresh.
            try:
                if (
                    analyze_queue is None
                    and now_monotonic - orchestrator_started_at >= 3600.0
                    and now_monotonic - last_analyze_at >= 86400.0
                ):
                    analyze_sweep_started_at = now_monotonic
                    analyze_queue = run_db_analyze_batch(None)
                elif analyze_queue and now_monotonic - analyze_sweep_started_at >= 300.0:
                    # Sweep blew past the 5min hard cap — abandon what's left
                    # and don't retry until the next 24hr window.
                    analyze_queue = None
                    last_analyze_at = now_monotonic
                elif analyze_queue:
                    analyze_queue = run_db_analyze_batch(analyze_queue)
                if analyze_queue is not None and not analyze_queue:
                    analyze_queue = None
                    last_analyze_at = now_monotonic
            except Exception:
                analyze_queue = None
                last_analyze_at = now_monotonic
            time.sleep(2.0)
            continue
        return 0
