from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import signal
import shutil
import sys
import threading
import time
from contextlib import nullcontext
from datetime import timedelta
from itertools import batched
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, TextIO, cast

from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from rich.console import Console
from rich.text import Text

from abxpkg.binary_service import BinaryEvent, BinaryRequestEvent, BinaryService
from abx_dl.events import (
    CrawlAbortEvent,
    CrawlCompletedEvent,
    CrawlEvent,
    CrawlPauseEvent,
    CrawlStartEvent,
    InstallEvent,
    MachineEvent,
    SnapshotCleanupEvent,
    SnapshotCompletedEvent,
    SnapshotEvent,
    slow_warning_timeout,
)
from abx_dl.catalog import PluginCatalog
from abx_dl.config import GlobalConfig, RuntimeConfig
from abx_dl.models import Snapshot as AbxSnapshot
from abx_dl.orchestrator import (
    compute_install_phase_timeout,
    compute_phase_timeout,
    create_bus,
    get_install_plugins,
    parse_input,
)
from abx_dl.services.binary_service import PluginBinaryEnvService
from abx_dl.services.archive_result_service import ArchiveResultService as HookArchiveResultService
from abx_dl.services.crawl_service import CrawlService as HookCrawlService
from abx_dl.services.crawl_lifecycle_service import CrawlLifecycleService
from abx_dl.services import PluginBinariesService
from abx_dl.services.process_service import ProcessService as HookProcessService
from abx_dl.services.snapshot_service import SnapshotService as HookSnapshotService
from abx_dl.cli import LiveBusUI
from abxbus import BaseEvent
from abxbus.event_bus import EventBus, get_current_event, in_handler_context
from abxbus.event_handler import EventHandlerAbortedError, EventHandlerCancelledError

from archivebox.services.resource_admission import RESOURCE_RECHECK_SECONDS, resource_admission

from archivebox.config.common import (
    ArchiveBoxBaseConfig,
    filter_crawl_env,
    normalize_runtime_config,
    _is_cookie_file_config_key,
    _plugin_enabled_config_keys,
)
from archivebox.base_models.models import PagedQuerySet
from archivebox.misc.db import run_db_analyze_batch
from archivebox.core.shutdown_util import foreground_shutdown_signals, raise_if_shutdown_requested
from archivebox.plugins.discovery import get_plugin_catalog
from archivebox.search.sonic_daemon import register_sonic_daemon_event_handler
from archivebox.workers.models import ACTIVE_STATE_LEASE_SECONDS
from archivebox.uuid_compat import compact_uuid
from archivebox.crawls.locks import crawl_lifecycle_lock

from .archive_result_service import ArchiveResultService
from .binary_service import ArchiveBoxBinaryService, project_abxpkg_derived_cache_to_db
from .crawl_service import CrawlService
from .machine_service import MachineService
from .process_service import ProcessService as PersistedProcessService
from .snapshot_service import SnapshotService
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
    elif crawl is not None:
        label = (crawl.label or "").strip()
        if not label:
            label = (crawl.urls or "").partition("\n")[0].strip() or str(crawl_id)
    else:
        label = str(crawl_id)
    line.append(_runner_label(label, reserve=prefix_width))
    Console(highlight=False).print(line)


def _count_selected_hooks(catalog: PluginCatalog, selected_plugins: list[str] | None) -> int:
    selected = catalog.select(selected_plugins) if selected_plugins else catalog
    return sum(1 for plugin in selected.values() for hook in plugin.hooks if "CrawlSetup" in hook.name or "Snapshot" in hook.name)


def _enable_requested_plugins(config: dict[str, Any], plugins: PluginCatalog) -> None:
    for plugin in plugins.values():
        if plugin.enabled_key in plugin.config.properties:
            config[plugin.enabled_key] = True


def _runner_task_context() -> contextvars.Context:
    context = contextvars.copy_context()
    context.run(EventBus.current_event_context.set, None)
    context.run(EventBus.current_handler_id_context.set, None)
    context.run(EventBus.current_eventbus_context.set, None)
    return context


def _is_external_task_cancelled(error: asyncio.CancelledError) -> bool:
    return not isinstance(error, (EventHandlerAbortedError, EventHandlerCancelledError))


async def _run_event_now(event, timeout: float | None = None):
    await event.now(timeout=timeout)
    await event.wait(timeout=timeout)
    await event.event_results_list()
    return event


def snapshot_attempt_timeout(plugins: PluginCatalog, config: dict[str, Any]) -> float:
    # The hard ceiling the runner gives one complete capture attempt.
    return compute_phase_timeout(plugins.hooks("Snapshot"), config) + 120.0


def ensure_background_runner() -> bool:
    from archivebox.machine.models import Machine, Process
    from archivebox.workers.supervisord_util import RUNNER_WORKER, get_existing_supervisord_process, get_worker, start_worker

    supervisor = get_existing_supervisord_process()
    runner_worker = get_worker(supervisor, "worker_runner") if supervisor else None
    if isinstance(runner_worker, dict) and runner_worker.get("statename") in ("STARTING", "RUNNING"):
        return False
    if supervisor is not None:
        start_worker(supervisor, RUNNER_WORKER())
        return True

    machine = Machine.current()
    Process.cleanup_stale_running(machine=machine)
    running_orchestrators = Process.objects.filter(
        machine=machine,
        status=Process.StatusChoices.RUNNING,
        process_type=Process.TypeChoices.ORCHESTRATOR,
    )
    if any(proc.is_running for proc in running_orchestrators):
        return False

    return False


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
        config_overrides: dict[str, Any] | None = None,
        schedule_all_crawls: bool = False,
        wait_for_resources: bool = True,
    ):
        self.crawl = crawl
        self.bus = create_bus(name=_bus_name("ArchiveBox", str(crawl.id)), total_timeout=3600.0)
        self.catalog = get_plugin_catalog()
        self.process_service = HookProcessService(
            self.bus,
            emit_jsonl=False,
            interactive_tty=interactive_interrupts,
            env_filter=filter_crawl_env,
            interrupted_hook_prompt=self._prompt_in_foreground if interactive_interrupts else None,
        )
        register_sonic_daemon_event_handler(self.bus)
        PersistedProcessService(self.bus)
        self.binary_process_service = ArchiveBoxBinaryService(self.bus)
        BinaryService(self.bus)
        TagService(self.bus)
        CrawlService(self.bus, crawl_id=str(crawl.id))
        MachineService(self.bus)
        self.process_discovered_snapshots_inline = process_discovered_snapshots_inline
        self.schedule_all_crawls = schedule_all_crawls
        self.wait_for_resources = wait_for_resources
        self._scheduler_yielded = False
        self.show_progress = show_progress
        self.interactive_interrupts = interactive_interrupts
        self._interrupt_choice: asyncio.Future[Literal["abort", "retry", "skip"]] | None = None
        self._user_aborted = False
        self._execution_interrupted = False
        self.bus.on(CrawlAbortEvent, self.on_CrawlAbortEvent)
        self.config_overrides = dict(config_overrides or {})

        self.snapshot_service = SnapshotService(
            self.bus,
            crawl_id=str(crawl.id),
            interrupted=self.execution_interrupted,
        )
        HookArchiveResultService(self.bus, emit_jsonl=False)
        ArchiveResultService(self.bus)
        self.requested_plugins = selected_plugins
        self.selected_plugins = selected_plugins
        self.initial_snapshot_ids = snapshot_ids
        self.snapshot_tasks: dict[str, asyncio.Task[None]] = {}
        self.snapshot_semaphore = asyncio.Semaphore(1)
        self.max_concurrent_snapshots = 1
        self._warmup_snapshot_id: str | None = None
        self._memory_baseline: int | None = None
        self._memory_peak_cost = 0
        self._observed_snapshot_cost: int | None = None
        self._resource_deferred = False
        self._initial_snapshot_admitted = False
        self.persona = None
        self.base_config: ArchiveBoxBaseConfig | dict[str, Any] = {}
        self.derived_config: dict[str, Any] = {}
        self.primary_url = ""
        self.crawl_output_dir = ""
        self._live_stream: TextIO | None = None
        self._live_ui: LiveBusUI | None = None
        self.root_crawl_event_id: str | None = None
        self.root_crawl_start_event_id: str | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._run_started = False
        self._skip_wait_until_idle = False
        # This is intentionally a synchronous OS-signal side channel, not bus
        # state. During SIGINT/SIGTERM/SIGHUP, asyncio.run() may already be
        # cancelling tasks and closing the loop, so abxbus cannot be relied on
        # for timely delivery of a final "stop now" event.
        self._signal_abort_requested = False
        self._last_lease_heartbeat_at = 0.0

    def execution_interrupted(self) -> bool:
        """Owner loss preserves work; handled stops retain the owner's terminal facts."""
        return self._execution_interrupted

    async def on_CrawlAbortEvent(self, event: CrawlAbortEvent) -> None:
        self._signal_abort_requested = True
        # abx-dl decides whether a required resource failed and settles that
        # attempt. Do not mistake its handled failure for a displaced worker:
        # that would discard the terminal fact and leave a dangling STARTED row.
        self._execution_interrupted = self._execution_interrupted or (not event.user_initiated and not event.error)
        # An abort can arrive while the prompt transport is being established,
        # before another SIGINT sees _interrupt_choice. Release that waiter too;
        # shutdown must never depend on a subsequent keypress or IPC response.
        if self._interrupt_choice is not None and not self._interrupt_choice.done():
            self._interrupt_choice.set_result("abort")
        if event.user_initiated:
            self._user_aborted = True
            # Exit 130 alone cannot distinguish a user's abort from a worker
            # displaced by takeover. Tell the owning add command explicitly
            # so it exits instead of reclaiming and restarting this crawl.
            if os.environ.get("SUPERVISOR_PROCESS_NAME"):
                (sys.__stderr__ or sys.stderr).write("ARCHIVEBOX_CRAWL_ABORTED\n")
                (sys.__stderr__ or sys.stderr).flush()

    def _interrupt_hook(self) -> None:
        if self._user_aborted:
            # An explicit abort is already draining hook groups with normal
            # grace periods. A further Ctrl+C requests immediate force exit.
            # This service owns only this runner's hook groups and children;
            # a server's supervisor or another foreground command is outside
            # the boundary. Tell a supervising add parent this was user intent
            # before bypassing the worker's normal finalization path.
            if os.environ.get("SUPERVISOR_PROCESS_NAME"):
                os.write((sys.__stderr__ or sys.stderr).fileno(), b"ARCHIVEBOX_CRAWL_ABORTED\n")
            os.write((sys.__stderr__ or sys.stderr).fileno(), b"\n[!] Forcing aborted crawl to exit now.\n")
            self.process_service.force_kill_owned_processes()
            os._exit(130)
        if self._run_task is None:
            # The crawl is already draining/finalizing; there is no live bus on
            # which to reopen a prompt. Remember the user's abort and finish the
            # cleanup that is already in progress. In particular do not hand a
            # second signal to Python's default handler in this teardown window.
            self._user_aborted = True
            if os.environ.get("SUPERVISOR_PROCESS_NAME"):
                os.write((sys.__stderr__ or sys.stderr).fileno(), b"ARCHIVEBOX_CRAWL_ABORTED\n")
            stream = self._live_stream if self._live_stream is not None and not self._live_stream.closed else (sys.__stderr__ or sys.stderr)
            os.write(stream.fileno(), b"\nAborting crawl - finishing shutdown... Ctrl+C again to force exit.\n")
            return
        if self._interrupt_choice is not None:
            self._choose_interrupt_action("abort")
            return

        async def dispatch() -> None:
            # ArchiveBox transports terminal intent; abx-dl alone decides pause
            # versus abort. No local counter may compete with its controller.
            await self.bus.emit(CrawlPauseEvent()).now()

        asyncio.get_running_loop().create_task(dispatch())

    async def _prompt_in_foreground(self, hook_name: str) -> Literal["abort", "retry", "skip"]:
        rendered = self._live_ui.show_interrupt_prompt(hook_name) if self._live_ui is not None else False
        if sys.stdin.isatty():
            # Direct run is itself the outer terminal owner. Keep its asyncio
            # loop alive so background completions render above the prompt. No
            # supervisor parent exists here to consume an IPC prompt request.
            choice = (
                await HookProcessService.read_interrupt_choice(
                    hook_name,
                    render=not rendered,
                    is_active=lambda: not self._signal_abort_requested,
                    on_abort=lambda: setattr(self, "_user_aborted", True),
                )
                or "abort"
            )
            if choice == "abort":
                # Also cover an inactive prompt that defaulted to abort. A
                # typed answer is recorded at the keypress by on_abort above.
                self._user_aborted = True
            return choice
        # A supervised worker has log pipes instead of terminal input. Its add
        # parent owns the same shared reader and returns the answer via signals.
        self._interrupt_choice = asyncio.get_running_loop().create_future()
        (sys.__stderr__ or sys.stderr).write(
            "ARCHIVEBOX_HOOK_INTERRUPTED " + json.dumps({"hook_name": hook_name, "rendered": rendered}) + "\n",
        )
        (sys.__stderr__ or sys.stderr).flush()
        try:
            return await self._interrupt_choice
        finally:
            self._interrupt_choice = None

    def _choose_interrupt_action(self, choice: Literal["abort", "retry", "skip"]) -> None:
        if self._interrupt_choice is not None and not self._interrupt_choice.done():
            if choice == "abort":
                self._user_aborted = True
            self._interrupt_choice.set_result(choice)

    def _request_abort_from_signal(self, sig: signal.Signals) -> None:
        # TERM cooperatively stops this owner; abx-dl drains its processes while
        # their bus is still available. This is best effort, not the correctness
        # boundary: SIGKILL/power loss may interrupt any await, so startup retires
        # stale Process rows and the next owner restarts the whole snapshot.
        # SIGINT instead uses the shared interactive/whole-abort controller.
        # Takeover/parent loss stops this execution owner, not the user's crawl
        # intent. Do not set _user_aborted or emit ARCHIVEBOX_CRAWL_ABORTED here:
        # the outer add may need to wait for the new owner and reclaim afterward.
        # Cancellation intentionally bypasses the interactive pause gate; a
        # waiting prompt must never keep a displaced worker or its hooks alive.
        self._signal_abort_requested = True
        self._execution_interrupted = True
        self._skip_wait_until_idle = True
        if not self._run_started and os.environ.get("ARCHIVEBOX_RUNNER_DAEMON") == "1":
            # A signal before run() starts has no async task or hooks to drain.
            # It must still be an unexpected supervisor exit, not a clean idle exit.
            raise SystemExit(128 + sig.value)
        # The foreground signal handler runs while the event loop may be in the
        # middle of shutdown. Flip cheap in-memory flags here and let normal
        # finally blocks do cleanup. Interactive SIGINT uses _interrupt_hook;
        # actual shutdown signals must cancel promptly in either mode.
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()

    async def crawl_is_cancelled(self) -> bool:
        from archivebox.crawls.models import Crawl

        if self._signal_abort_requested:
            return True
        if self.allow_maintenance_on_inactive_crawl:
            # SEALED is the normal terminal state of a finished crawl, not a
            # cancellation signal for maintenance work on its already-sealed
            # snapshots (plugin backfill, fs migration, etc.). When the runner
            # is given explicit snapshot_ids + selected_plugins, the caller has
            # deliberately scoped work that remains valid after crawl sealing.
            return False
        return await Crawl.objects.filter(id=self.crawl.id, status=Crawl.StatusChoices.SEALED).aexists()

    async def crawl_is_paused(self) -> bool:
        from archivebox.crawls.models import Crawl

        crawl = await Crawl.objects.only("status").aget(id=self.crawl.id)
        return crawl.is_paused

    async def watch_for_cancelled_crawl(self, parent_event: BaseEvent, *, poll_interval: float = 1.0) -> None:
        while True:
            await asyncio.sleep(poll_interval)
            # A received control event already stopped admission. Echoing that
            # local flag as a new takeover would suppress abx-dl's terminal
            # facts during cleanup. This watcher only translates DB changes.
            if self._signal_abort_requested:
                return
            if not await self.crawl_is_cancelled():
                continue
            abort_event = parent_event.emit(CrawlAbortEvent(user_initiated=False))
            await _run_event_now(abort_event, abort_event.event_timeout)
            return

    @property
    def allow_maintenance_on_inactive_crawl(self) -> bool:
        """Run explicitly targeted plugin work on already-sealed snapshots."""
        return bool(
            self.initial_snapshot_ids and self.selected_plugins and self.crawl.status == self.crawl.StatusChoices.SEALED,
        )

    async def run(self) -> None:
        root_snapshot_id: str | None = None
        bus_destroyed = False
        run_state_loaded = False
        self._run_task = asyncio.current_task()
        self._run_started = True
        # Do not raise KeyboardInterrupt directly from an OS signal while
        # the asyncio loop is active. Python can inject it into whichever
        # task is currently running, which produces noisy "Task exception
        # was never retrieved" logs from unrelated abxbus housekeeping
        # tasks. _request_abort_from_signal() cancels the runner task
        # cooperatively instead; repeated signals still hard-exit in the
        # shared foreground signal handler.
        # Keep signal ownership through bus destruction AND durable finalization.
        # Restoring the outer/default handler before those awaits leaves a real
        # race: a rapid second Ctrl+C can kill Python during teardown, producing
        # supervisor exit -1 / shell 255 instead of an acknowledged user abort.
        with foreground_shutdown_signals(
            first_signal_message="\n[🛑] Got {signal_name}, stopping crawl worker...\n",
            on_signal=self._request_abort_from_signal,
            interrupt_handlers={
                signal.SIGINT: self._interrupt_hook,
                **(
                    {
                        signal.SIGUSR1: lambda: self._choose_interrupt_action("skip"),
                        signal.SIGUSR2: lambda: self._choose_interrupt_action("retry"),
                    }
                    if self.interactive_interrupts
                    else {}
                ),
            },
            raise_on_first_signal=False,
        ):
            try:
                if not await self.wait_for_resource_admission():
                    return
                # Startup and its first snapshot are one admission. Browser
                # startup can itself cause reclaim; checking again immediately
                # would tear it down and repeat startup without doing any work.
                self._initial_snapshot_admitted = True
                run_state_loaded = True
                snapshot_ids = await sync_to_async(self.load_run_state, thread_sensitive=True)()
                # Reuse the cost this process already learned even when a limit
                # is configured: the limit caps concurrency, it is not a reason
                # to re-measure. Otherwise every crawl start (switch, restart,
                # new submission) ran a solo warmup capture at half throughput.
                self._observed_snapshot_cost = resource_admission.observed_snapshot_cost
                max_concurrent_snapshots = resource_admission.snapshot_limit(int(self.base_config.get("CRAWL_MAX_CONCURRENT_SNAPSHOTS", 0)))
                self.max_concurrent_snapshots = max_concurrent_snapshots
                self.snapshot_semaphore = asyncio.Semaphore(max_concurrent_snapshots)
                live_ui = self._create_live_ui()
                self._live_ui = live_ui
                with live_ui if live_ui is not None else nullcontext():
                    try:
                        if snapshot_ids:
                            root_snapshot_id = snapshot_ids[0]
                            await self.run_crawl(root_snapshot_id, snapshot_ids)
                    finally:
                        self._run_task = None
                        try:
                            # Cancelling scheduler wrappers does not await the
                            # bus-owned foreground hooks. Keep their bus alive
                            # until abx-dl has emitted and projected completion;
                            # an idle timeout cannot establish that ownership
                            # boundary. Abrupt loss still restarts on next claim.
                            # Stop before cancelling snapshot wrappers: their
                            # finally blocks unregister cleanup/control consumers
                            # that the still-running owners must retain.
                            await self.process_service.stop()
                            await self.bus.wait_until_idle(timeout=1.0 if self._skip_wait_until_idle else 30.0)
                            await self.binary_process_service.flush_missing_finalizers()
                        except TimeoutError:
                            pass
                        finally:
                            await self.stop_snapshot_tasks()
                            await self.bus.destroy(clear=False)
                            bus_destroyed = True
            finally:
                if not bus_destroyed:
                    self._run_task = None
                    try:
                        await self.process_service.stop()
                    finally:
                        await self.stop_snapshot_tasks()
                        await self.bus.destroy(clear=False)
                if self._live_stream is not None:
                    try:
                        self._live_stream.close()
                    except Exception:
                        pass
                    self._live_stream = None
                if run_state_loaded:
                    await sync_to_async(project_abxpkg_derived_cache_to_db, thread_sensitive=True)(self.base_config.get("ABXPKG_LIB_DIR"))
                    await sync_to_async(self.finalize_run_state, thread_sensitive=True)()
                if self._user_aborted:
                    raise KeyboardInterrupt

    async def wait_for_resource_admission(self) -> bool:
        # Foreground callers retain this bus and its observers while waiting.
        # Collection scheduling instead returns deferred work after cleanup so
        # the outer scheduler can reconsider all crawls using its normal order.
        while True:
            if await self.crawl_is_cancelled() or (await self.crawl_is_paused() and not self.allow_maintenance_on_inactive_crawl):
                return False
            self._resource_deferred = await sync_to_async(defer_crawl_for_resources, thread_sensitive=True)(
                self.crawl,
                required_memory=self._observed_snapshot_cost,
            )
            if not self._resource_deferred:
                return True
            if not self.wait_for_resources or self.schedule_all_crawls:
                return False
            await asyncio.sleep(RESOURCE_RECHECK_SECONDS)

    async def enqueue_snapshot(self, snapshot_id: str, crawl_start_event: CrawlStartEvent | None = None) -> None:
        # ORM queue reads return UUIDs; event records carry compact strings.
        # Use the shared UUID representation before task/lease lookup and the
        # preparation/cleanup guards, or later snapshots skip those projections.
        snapshot_id = str(compact_uuid(snapshot_id))
        if self._resource_deferred or self._scheduler_yielded:
            return
        if not self._initial_snapshot_admitted and await sync_to_async(defer_crawl_for_resources, thread_sensitive=True)(
            self.crawl,
            excluded_snapshot_ids=list(self.snapshot_tasks),
        ):
            self._resource_deferred = True
            return
        if await self.crawl_is_cancelled():
            return
        if await self.crawl_is_paused() and not self.allow_maintenance_on_inactive_crawl:
            return
        task = self.snapshot_tasks.get(snapshot_id)
        if task is not None and not task.done():
            return
        current_event = crawl_start_event or get_current_event()
        if not isinstance(current_event, CrawlStartEvent) and in_handler_context():
            return
        if not any(not task.done() for task in self.snapshot_tasks.values()):
            self._memory_baseline = resource_admission.process_tree_memory()
            self._memory_peak_cost = 0
            if self._observed_snapshot_cost is None:
                self._warmup_snapshot_id = snapshot_id
        else:
            # Whole-workload growth cannot identify one capture's cost once
            # captures overlap. Retain the largest isolated measurement and
            # resume learning only when a new capture starts from idle.
            self._observe_snapshot_memory()
            self._memory_baseline = None
        if isinstance(current_event, CrawlStartEvent):
            task = asyncio.create_task(self.run_snapshot(snapshot_id, current_event), context=_runner_task_context())
        else:
            task = asyncio.create_task(self.run_snapshot(snapshot_id), context=_runner_task_context())
        self._initial_snapshot_admitted = False
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

    async def wait_for_snapshot_tasks(self, *, enqueue_projected: bool = True) -> None:
        task_errors: list[Exception] = []
        stop_scheduling = False
        while True:
            pending_tasks: list[asyncio.Task[None]] = []
            for snapshot_id, task in list(self.snapshot_tasks.items()):
                if task.done():
                    if self.snapshot_tasks.get(snapshot_id) is task:
                        self.snapshot_tasks.pop(snapshot_id, None)
                    self._finish_warmup_snapshot(snapshot_id)
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
                if self._resource_deferred and not await self.wait_for_resource_admission():
                    return
                if enqueue_projected:
                    await self.enqueue_pending_snapshots_from_projection()
                if self._resource_deferred and self.wait_for_resources and not self.schedule_all_crawls:
                    continue
                if not self.snapshot_tasks:
                    return
                continue
            await self.heartbeat_active_leases()
            self._observe_snapshot_memory()
            done, _pending = await asyncio.wait(pending_tasks, timeout=RESOURCE_RECHECK_SECONDS, return_when=asyncio.FIRST_COMPLETED)
            self._observe_snapshot_memory()
            if not done:
                if enqueue_projected and not stop_scheduling:
                    await self.enqueue_pending_snapshots_from_projection()
                continue
            for task in done:
                for snapshot_id, tracked_task in list(self.snapshot_tasks.items()):
                    if tracked_task is task:
                        self.snapshot_tasks.pop(snapshot_id, None)
                        self._finish_warmup_snapshot(snapshot_id)
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
            if not stop_scheduling and enqueue_projected:
                await self.enqueue_pending_snapshots_from_projection()

    def _observe_snapshot_memory(self) -> None:
        if self._memory_baseline is None:
            return
        used = resource_admission.process_tree_memory()
        if used is not None:
            # Only attribute this workload's growth to a capture. Other jobs on
            # the host reduce available headroom, but are not a per-capture cost
            # to multiply again for every snapshot we want to admit.
            self._memory_peak_cost = max(
                self._memory_peak_cost,
                used - self._memory_baseline,
            )
            if self._observed_snapshot_cost is not None:
                self._observed_snapshot_cost = max(self._observed_snapshot_cost, self._memory_peak_cost)

    def _finish_warmup_snapshot(self, snapshot_id: str) -> None:
        self._observe_snapshot_memory()
        # Only isolated captures teach a per-snapshot cost. Reuse it across
        # crawls, with slow decay so one expensive capture is not a lifetime cap.
        if self._memory_baseline is not None and self._memory_peak_cost > 0:
            resource_admission.observed_snapshot_cost = max(
                self._memory_peak_cost,
                int((resource_admission.observed_snapshot_cost or 0) * 0.9),
            )
            self._observed_snapshot_cost = resource_admission.observed_snapshot_cost
            logging.getLogger(__name__).info(
                "Snapshot admission: concurrency limit=%s, observed memory growth=%s bytes",
                self.max_concurrent_snapshots,
                self._observed_snapshot_cost,
            )
        self._warmup_snapshot_id = None

    async def heartbeat_active_leases(self) -> None:
        # These are restartable work-item leases, not orchestrator-election
        # heartbeats. Each update is a short autocommit statement; network and
        # filesystem work continues outside a database transaction. A future
        # PostgreSQL multi-machine runner uses these Crawl/Snapshot claims as
        # its coordination boundary while SQLite keeps one local orchestrator.
        if self._run_task is None:
            return
        now_monotonic = time.monotonic()
        if now_monotonic - self._last_lease_heartbeat_at < 10.0:
            return
        self._last_lease_heartbeat_at = now_monotonic
        lease_until = timezone.now() + timedelta(seconds=ACTIVE_STATE_LEASE_SECONDS)
        active_snapshot_ids = [snapshot_id for snapshot_id, task in self.snapshot_tasks.items() if not task.done()]

        from archivebox.crawls.models import Crawl

        await Crawl.objects.filter(id=self.crawl.id, status=Crawl.StatusChoices.STARTED).aupdate(
            retry_at=lease_until,
            modified_at=timezone.now(),
        )
        for snapshot_id in active_snapshot_ids:
            renewed = await self.snapshot_service.renew_lease(snapshot_id, lease_until)
            if renewed is False:
                task = self.snapshot_tasks.get(snapshot_id)
                if task is not None and not task.done():
                    task.cancel()

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

        if self._resource_deferred or self._scheduler_yielded:
            return
        if not isinstance(get_current_event(), CrawlStartEvent):
            return
        if await self.crawl_is_cancelled():
            return
        if await self.crawl_is_paused() and not self.allow_maintenance_on_inactive_crawl:
            return

        await sync_to_async(self.crawl.refresh_from_db, thread_sensitive=True)()
        config = await sync_to_async(lambda: get_config(crawl=self.crawl), thread_sensitive=True)()
        self.max_concurrent_snapshots = resource_admission.snapshot_limit(int(config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"]))

        active_snapshot_ids = [snapshot_id for snapshot_id, task in self.snapshot_tasks.items() if not task.done()]
        available_slots = resource_admission.additional_snapshot_slots(
            self.max_concurrent_snapshots,
            len(active_snapshot_ids),
            self._observed_snapshot_cost,
            crawl_id=str(self.crawl.id),
        )
        if available_slots <= 0:
            if not active_snapshot_ids:
                self._resource_deferred = await sync_to_async(defer_crawl_for_resources, thread_sensitive=True)(
                    self.crawl,
                    required_memory=self._observed_snapshot_cost,
                )
            return
        if self.schedule_all_crawls and await sync_to_async(_higher_priority_crawl_waiting, thread_sensitive=True)(
            str(self.crawl.id),
            active_snapshot_ids,
        ):
            # Finish every admitted capture before normal crawl cleanup. The
            # outer scheduler can then apply its existing ordering instead of
            # waiting for this crawl's entire backlog to drain. Keep the same
            # browser/session when this crawl still owns the next admission.
            self._scheduler_yielded = True
            return
        # Explicit plugin requests are capture work even on sealed snapshots.
        # Consume them in the same crawl; ordinary sealed maintenance still waits.
        # Within-crawl FIFO breadth-first; policy above _first_due_id.
        pending_snapshot_ids = await sync_to_async(
            lambda: list(
                self.crawl.snapshot_set.filter(
                    Q(status__in=Snapshot.RUNNABLE_STATES)
                    | Q(status=Snapshot.StatusChoices.SEALED, config__RETRY_PLUGINS__0__isnull=False),
                )
                .exclude(id__in=active_snapshot_ids)
                .filter(retry_at__lte=timezone.now())
                .order_by("depth", "created_at", "pk")
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
        from archivebox.plugins.discovery import get_enabled_plugins
        from archivebox.machine.models import Machine, NetworkInterface, Process

        self.primary_url = self.crawl.get_urls_list()[0] if self.crawl.get_urls_list() else ""
        # Validate saved binary paths at the execution boundary, including
        # config edited since this process first registered its Machine.
        machine = Machine._sanitize_config(Machine.current())
        current_iface = NetworkInterface.current(refresh=not self.allow_maintenance_on_inactive_crawl)
        current_process = Process.current()
        if current_process.iface_id != current_iface.id or current_process.machine_id != current_iface.machine_id:
            current_process.iface = current_iface
            current_process.machine = current_iface.machine
            current_process.save(update_fields=["iface", "machine", "modified_at"])
        self.persona = self.crawl.resolve_persona()
        self.base_config = get_config(crawl=self.crawl, overrides=self.config_overrides)
        # The merged user payload owns auth paths and binary selections. The
        # install phase publishes resolved binaries; stale machine paths must
        # not override explicit runtime settings before that phase runs.
        self.derived_config = {
            key: value
            for key, value in (machine.config or {}).items()
            if key not in {"SECRET_KEY", "_SECRET_KEY_DB"}
            and not _is_cookie_file_config_key(key)
            and (not key.endswith("_BINARY") or value == self.base_config.get(key))
        }
        # Crawl.output_dir no longer probes for pre-0.9.4 hyphenated dirs (it
        # is read by request handlers). Link one into place before writing.
        self.crawl.migrate_legacy_output_dir()
        self.crawl_output_dir = str(self.crawl.output_dir)
        Path(self.crawl_output_dir).mkdir(parents=True, exist_ok=True)
        if self.selected_plugins is None:
            raw_plugins = str(self.base_config.get("PLUGINS") or "").strip()
            if raw_plugins:
                self.selected_plugins = [name.strip() for name in raw_plugins.split(",") if name.strip()]
            else:
                enabled_plugins = get_enabled_plugins(config=self.base_config)
                runtime_events = ("CrawlSetup", "CrawlCleanup", "Snapshot", "SnapshotCleanup")
                runtime_plugins = {
                    plugin.name for event_name in runtime_events for plugin, _hook in self.catalog.hooks(event_name, names=enabled_plugins)
                }
                self.selected_plugins = sorted(runtime_plugins) or None
        if self.crawl.is_paused:
            return []
        if self.initial_snapshot_ids:
            # Explicit ids select normal runnable work, except for the one
            # targeted maintenance admitted by allow_maintenance_on_inactive_crawl.
            snapshot_ids = [str(snapshot_id) for snapshot_id in self.initial_snapshot_ids]
        else:
            # Within-crawl FIFO breadth-first; policy above _first_due_id.
            pending_snapshots = list(
                self.crawl.snapshot_set.filter(
                    Q(status__in=Snapshot.RUNNABLE_STATES)
                    | Q(status=Snapshot.StatusChoices.SEALED, config__RETRY_PLUGINS__0__isnull=False),
                )
                .filter(retry_at__lte=timezone.now())
                .order_by("depth", "created_at", "pk"),
            )
            if pending_snapshots:
                snapshot_ids = [str(snapshot.id) for snapshot in pending_snapshots]
            else:
                if self.crawl.snapshot_set.exclude(status__in=[Snapshot.StatusChoices.SEALED, Snapshot.StatusChoices.PAUSED]).exists():
                    return []
                created = self.create_initial_snapshots()
                snapshots = created or list(self.crawl.snapshot_set.filter(depth__in=[0, 1]).order_by("depth", "created_at", "pk"))
                snapshot_ids = [str(snapshot.id) for snapshot in snapshots]
        # Parse and deduplicate before copying browser state. An empty import
        # has no capture runtime to prepare; a large persona otherwise blocks
        # the collection scheduler just to be deleted during finalization.
        if snapshot_ids and self.persona:
            self.base_config.update(
                self.persona.prepare_runtime_for_crawl(
                    self.crawl,
                    chrome_binary=self.base_config["CHROME_BINARY"],
                ),
            )
        return snapshot_ids

    def create_initial_snapshots(self) -> list:
        from archivebox.misc.util import validate_url

        if self.crawl.snapshot_set.exists():
            return []

        # Plain URL lists need no parser subprocess. Every other submitted
        # document is parsed by abx-dl and returned as discovery facts; only
        # those facts cross the ArchiveBox persistence boundary.
        parser_name = str(self.base_config.get("PARSER") or "auto").strip().lower()
        direct_urls: list[str] = []
        if parser_name in {"auto", "url_list"}:
            for line in (self.crawl.urls or "").splitlines():
                raw_line = line.strip()
                if not raw_line or raw_line.startswith("#"):
                    continue
                try:
                    direct_urls.append(validate_url(raw_line))
                except ValueError:
                    direct_urls = []
                    break

        if direct_urls:
            return self.crawl.create_discovered_snapshots(
                None,
                ({"url": url} for url in direct_urls),
                depth=0,
            )

        parser_catalog = self.catalog
        if parser_name not in {"auto", "url_list"}:
            requested = parser_name if parser_name.startswith("parse_") else f"parse_{parser_name}_urls"
            parser_catalog = self.catalog.select([requested])
        assert isinstance(self.base_config, ArchiveBoxBaseConfig)
        runtime_config = self.base_config.for_crawl_runtime(
            crawl=self.crawl,
            persona=self.persona,
            crawl_output_dir=self.crawl.output_dir,
        )
        discovered = asyncio.run(
            parse_input(
                self.crawl.urls,
                parser_catalog,
                self.crawl.output_dir / "input",
                config=normalize_runtime_config(runtime_config),
                derived_config=normalize_runtime_config(self.derived_config),
                runtime="archivebox",
                auto_install=True,
                emit_jsonl=False,
                env_filter=filter_crawl_env,
            ),
        )
        records = [snapshot.model_dump(mode="json") for snapshot in discovered]
        created = self.crawl.create_discovered_snapshots(None, records, depth=0)
        if created:
            self.primary_url = created[0].url
        return created

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
        # An empty/deduplicated intake never started an execution lifecycle.
        # Retire that queue row without preparing a browser. For actual captures,
        # only the CrawlCompleted projector may seal, never this shutdown path.
        if not crawl.snapshot_set.exists():
            if crawl.status != Crawl.StatusChoices.SEALED:
                if crawl.status == Crawl.StatusChoices.STARTED:
                    crawl.seal()
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
        stream = sys.stderr if stderr_is_tty or not stdout_is_tty else sys.stdout
        progress_tty = os.environ.get("ARCHIVEBOX_PROGRESS_TTY")
        if progress_tty or (interactive_tty and os.path.exists("/dev/tty")):
            try:
                self._live_stream = open(progress_tty or "/dev/tty", "w", buffering=1, encoding=stream.encoding or "utf-8")
                stream = self._live_stream
                interactive_tty = stream.isatty()
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
            force_terminal=interactive_tty,
            width=terminal_width,
            height=terminal_height,
            _environ={
                "COLUMNS": str(terminal_width),
                "LINES": str(terminal_height),
            },
        )
        plugins_label = ", ".join(self.selected_plugins) if self.selected_plugins else f"all ({len(self.catalog)} available)"
        live_ui = LiveBusUI(
            self.bus,
            total_hooks=_count_selected_hooks(self.catalog, self.selected_plugins),
            timeout_seconds=self.base_config["TIMEOUT"],
            ui_console=ui_console,
            interactive_tty=interactive_tty,
        )
        live_ui.print_intro(
            url=self.primary_url or "crawl",
            output_dir=Path(self.crawl_output_dir),
            plugins_label=plugins_label,
        )
        return live_ui

    async def load_snapshot_payload(self, snapshot_id: str, *, prepare: bool = True) -> dict[str, Any]:
        from archivebox.config.common import get_config
        from archivebox.core.models import Snapshot

        def load_context():
            snapshot = Snapshot.objects.select_related("crawl", "crawl__created_by", "crawl__persona").get(id=snapshot_id)
            persona = snapshot.crawl.persona
            base_config = get_config(crawl=snapshot.crawl, snapshot=snapshot, persona=persona, overrides=self.config_overrides)
            local_root = None
            if persona and str(base_config.get("CHROME_ISOLATION") or "crawl").lower() == "snapshot":
                local_root = (
                    persona.local_runtime_root_for_crawl(snapshot.crawl).parent.parent
                    / "snapshots"
                    / str(snapshot.id)
                    / ".persona"
                    / persona.name
                )
            return snapshot, persona, base_config, snapshot.tags_str(), local_root

        snapshot, persona, base_config, tags, local_root = await sync_to_async(load_context, thread_sensitive=True)()

        def prepare_payload(*, create_outputs: bool = True):
            # Persona copies and remote archive metadata must not occupy the one
            # thread used by unrelated result writes. Keep ORM reads above and
            # use this snapshot's materialized context, not mutable runner state.
            if create_outputs:
                snapshot.crawl.migrate_legacy_output_dir()
            runtime_chrome_overrides = {}
            if persona:
                if create_outputs and str(base_config.get("CHROME_ISOLATION") or "crawl").lower() == "snapshot":
                    runtime_chrome_overrides.update(
                        persona.prepare_runtime_for_snapshot(
                            snapshot,
                            chrome_binary=base_config["CHROME_BINARY"],
                            local_root=local_root,
                        ),
                    )
                else:
                    crawl_downloads_dir = persona.runtime_downloads_dir_for_crawl(snapshot.crawl)
                    if create_outputs:
                        crawl_downloads_dir.mkdir(parents=True, exist_ok=True)
                    runtime_chrome_overrides.update(
                        {
                            "PERSONAS_DIR": str(persona.runtime_root_for_crawl(snapshot.crawl).parent),
                            "ACTIVE_PERSONA": persona.name,
                        },
                    )
            snapshot_output_dir = str(snapshot.output_dir)
            if create_outputs:
                Path(snapshot_output_dir).mkdir(parents=True, exist_ok=True)
            config = base_config.for_crawl_runtime(
                crawl=snapshot.crawl,
                snapshot=snapshot,
                persona=persona,
                runtime_overrides=runtime_chrome_overrides,
                extra_context={
                    "snapshot_id": str(snapshot.id),
                },
            )
            normalized_config = normalize_runtime_config(config)
            configured_plugins = [name.strip().lower() for name in str(normalized_config.get("PLUGINS") or "").split(",") if name.strip()]
            if configured_plugins:
                selected_plugin_names = set(self.catalog.select(configured_plugins))
                for plugin_name, enabled_key in _plugin_enabled_config_keys().items():
                    normalized_config.setdefault(enabled_key, plugin_name in selected_plugin_names)
            return {
                "id": str(snapshot.id),
                "url": snapshot.url,
                "title": snapshot.title,
                "timestamp": snapshot.timestamp,
                "bookmarked_at": snapshot.bookmarked_at.isoformat() if snapshot.bookmarked_at else "",
                "created_at": snapshot.created_at.isoformat() if snapshot.created_at else "",
                "tags": tags,
                "depth": snapshot.depth,
                "status": snapshot.status,
                "retry_at": snapshot.retry_at,
                "output_dir": snapshot_output_dir,
                "config": normalized_config,
                "selected_plugins": [name.strip() for name in str((snapshot.config or {}).get("PLUGINS") or "").split(",") if name.strip()],
                "retry_plugins": list((snapshot.config or {}).get("RETRY_PLUGINS") or []),
                "_snapshot": snapshot,
            }

        if prepare:
            return await asyncio.to_thread(prepare_payload)
        payload = await asyncio.to_thread(prepare_payload, create_outputs=False)
        payload["_prepare"] = prepare_payload
        return payload

    async def run_crawl(self, root_snapshot_id: str, snapshot_ids: list[str]) -> None:
        snapshot = await self.load_snapshot_payload(root_snapshot_id, prepare=False)
        config = normalize_runtime_config(snapshot["config"])
        derived_config = normalize_runtime_config(self.derived_config)
        output_dir = Path(self.crawl_output_dir)
        plugins = self.catalog.select(self.selected_plugins)
        config["ABX_RUNTIME"] = "archivebox"
        if self.requested_plugins is not None:
            _enable_requested_plugins(config, plugins)
        setup_hooks = plugins.hooks("CrawlSetup")
        abx_snapshot = AbxSnapshot(
            id=snapshot["id"],
            url=snapshot["url"],
            depth=int(snapshot["depth"]),
            crawl_id=str(self.crawl.id),
        )
        crawl_setup_phase_timeout = compute_phase_timeout(setup_hooks, config)
        max_snapshot_count = max(1, int(config.get("CRAWL_MAX_URLS") or len(snapshot_ids) or 1))
        snapshot_phase_timeout = snapshot_attempt_timeout(plugins, config)
        all_snapshots_phase_timeout = snapshot_phase_timeout * max_snapshot_count
        crawl_cleanup_phase_timeout = crawl_setup_phase_timeout
        crawl_lifecycle_timeout = (
            crawl_setup_phase_timeout
            + all_snapshots_phase_timeout
            + crawl_cleanup_phase_timeout
            + CrawlCompletedEvent.model_fields["event_timeout"].default
            + 30.0
        )
        await self.bus.emit(MachineEvent(config=config, config_type="user")).now()
        if derived_config:
            await self.bus.emit(MachineEvent(config=derived_config, config_type="derived")).now()
        if plugins:
            install_plugins = get_install_plugins(plugins)
            install_timeout = compute_install_phase_timeout(install_plugins, config)
            PluginBinaryEnvService(self.bus, catalog=plugins)
            PluginBinariesService(
                self.bus,
                catalog=plugins,
                auto_install=True,
                install_plugins=install_plugins,
                output_dir=output_dir,
                snapshot=abx_snapshot,
                abort_requested=self.crawl_is_cancelled,
                # A broken optional extractor must not restart the entire crawl.
                continue_on_binary_error=True,
            )
            await _run_event_now(
                self.bus.emit(
                    InstallEvent(
                        url=snapshot["url"],
                        snapshot_id=snapshot["id"],
                        output_dir=str(output_dir),
                        event_timeout=install_timeout,
                        event_handler_slow_timeout=slow_warning_timeout(install_timeout),
                    ),
                ),
                install_timeout,
            )
        HookCrawlService(
            self.bus,
            url=snapshot["url"],
            snapshot=abx_snapshot,
            output_dir=output_dir,
            catalog=plugins,
            abort_requested=self.crawl_is_cancelled,
        )

        async def run_snapshots(event: CrawlStartEvent) -> None:
            self.root_crawl_start_event_id = event.event_id
            scheduling_error: BaseException | None = None
            try:
                if self.initial_snapshot_ids is not None:
                    next_snapshot = 0
                    while True:
                        slots = resource_admission.additional_snapshot_slots(
                            self.max_concurrent_snapshots,
                            0,
                            self._observed_snapshot_cost,
                            crawl_id=str(self.crawl.id),
                        )
                        if self._initial_snapshot_admitted:
                            # Startup and its first snapshot already passed the same
                            # admission before allocating the crawl browser.
                            slots = max(1, slots)
                        if not slots and next_snapshot < len(snapshot_ids):
                            if not await self.wait_for_resource_admission():
                                return
                            continue
                        batch = snapshot_ids[next_snapshot : next_snapshot + slots]
                        if not batch:
                            return
                        for snapshot_id in batch:
                            if await self.crawl_is_cancelled():
                                return
                            if await self.crawl_is_paused() and not self.allow_maintenance_on_inactive_crawl:
                                return
                            await self.enqueue_snapshot(snapshot_id)
                            if self._resource_deferred:
                                break
                            next_snapshot += 1
                        await self.wait_for_snapshot_tasks(enqueue_projected=False)
                        if self._resource_deferred:
                            return
                else:
                    slots = resource_admission.additional_snapshot_slots(
                        self.max_concurrent_snapshots,
                        0,
                        self._observed_snapshot_cost,
                        crawl_id=str(self.crawl.id),
                    )
                    if self._initial_snapshot_admitted:
                        slots = max(1, slots)
                    for snapshot_id in snapshot_ids[:slots]:
                        if await self.crawl_is_cancelled():
                            break
                        if await self.crawl_is_paused():
                            break
                        await self.enqueue_snapshot(snapshot_id)
                    await self.wait_for_snapshot_tasks()

            except BaseException as error:
                scheduling_error = error
                raise
            finally:
                # Pausing admission must still settle already admitted tasks;
                # this is a scheduler barrier, not a terminal-state decision.
                try:
                    await self.drain_snapshot_tasks()
                except BaseException as drain_error:
                    if scheduling_error is None:
                        raise
                    scheduling_error.add_note(f"Snapshot tasks also failed: {drain_error}")

        # abx-dl owns phase ordering and completion. ArchiveBox supplies only
        # queue admission and waits for those admitted snapshots to settle.
        CrawlLifecycleService(
            self.bus,
            url=snapshot["url"],
            snapshot=abx_snapshot,
            output_dir=output_dir,
            crawl_setup_phase_timeout=crawl_setup_phase_timeout,
            snapshot_phase_timeout=all_snapshots_phase_timeout,
            crawl_cleanup_phase_timeout=crawl_cleanup_phase_timeout,
            abort_requested=self.crawl_is_cancelled,
            run_snapshots=run_snapshots,
        )

        crawl_event = CrawlEvent(
            url=snapshot["url"],
            snapshot_id=snapshot["id"],
            output_dir=str(output_dir),
            event_timeout=crawl_lifecycle_timeout,
            event_handler_timeout=crawl_lifecycle_timeout + 30.0,
            event_handler_slow_timeout=slow_warning_timeout(crawl_lifecycle_timeout),
        )
        self.root_crawl_event_id = crawl_event.event_id
        cancel_watcher = asyncio.create_task(self.watch_for_cancelled_crawl(crawl_event))
        try:
            await _run_event_now(self.bus.emit(crawl_event), None)
        finally:
            cancel_watcher.cancel()
            await asyncio.gather(cancel_watcher, return_exceptions=True)
        if await self.crawl_is_cancelled():
            self._skip_wait_until_idle = True
            return

    async def run_snapshot(self, snapshot_id: str, crawl_start_event: CrawlStartEvent | None = None) -> None:
        async with self.snapshot_semaphore:
            parent_event = crawl_start_event or get_current_event()
            if not isinstance(parent_event, CrawlStartEvent):
                raise RuntimeError("Snapshot events must be emitted from a CrawlStartEvent handler")
            crawl_start_event = parent_event
            snapshot = await self.load_snapshot_payload(snapshot_id, prepare=False)
            try:
                await sync_to_async(snapshot["_snapshot"].validate_url_for_archiving, thread_sensitive=True)()
            except ValidationError as err:
                if snapshot["status"] != "sealed":
                    await sync_to_async(snapshot["_snapshot"].seal, thread_sensitive=True)()
                print(f"[X] Refusing to archive invalid Snapshot URL {snapshot['url']!r}: {err}", file=sys.stderr)
                return
            if snapshot["status"] == "sealed" and not self.selected_plugins and not snapshot["retry_plugins"]:
                await sync_to_async(run_snapshot_maintenance, thread_sensitive=True)(snapshot_id)
                return
            config = normalize_runtime_config(snapshot["config"])
            snapshot_selected_plugins = (
                self.requested_plugins or snapshot["retry_plugins"] or snapshot["selected_plugins"] or self.selected_plugins
            )
            # All remaining URLs share the crawl budget, including explicitly
            # submitted roots. abx-dl only enforces the current snapshot's size.
            if await sync_to_async(snapshot["_snapshot"].crawl.limit_stop_reason, thread_sensitive=True)(config=config) in (
                "crawl_max_size",
                "crawl_timeout",
            ):
                await sync_to_async(self.seal_snapshot_due_to_limit, thread_sensitive=True)(snapshot_id)
                return
            derived_config = normalize_runtime_config(self.derived_config)
            output_dir = Path(snapshot["output_dir"])
            plugins = self.catalog.select(snapshot_selected_plugins) if snapshot_selected_plugins else self.catalog
            if self.requested_plugins is not None:
                _enable_requested_plugins(config, plugins)
            abx_snapshot = AbxSnapshot(
                id=snapshot["id"],
                url=snapshot["url"],
                depth=int(snapshot["depth"]),
                crawl_id=str(self.crawl.id),
            )
            config["ABX_RUNTIME"] = "archivebox"
            snapshot_phase_timeout = snapshot_attempt_timeout(plugins, config)
            user_config_event = MachineEvent(config=config, config_type="user")
            user_config_event.event_parent_id = crawl_start_event.event_id
            await self.bus.emit(user_config_event).now()
            derived_config_event = None
            if derived_config:
                derived_config_event = MachineEvent(config=derived_config, config_type="derived")
                derived_config_event.event_parent_id = crawl_start_event.event_id
                await self.bus.emit(derived_config_event).now()

            async def prepare_snapshot(event: SnapshotEvent) -> None:
                if event.snapshot_id != snapshot_id:
                    return
                # Preparation is part of the attempt, not a preflight outside
                # its failure boundary. abx-dl sees this consumer's exception
                # and ends the attempt through its ordinary cleanup/completion.
                prepared = await asyncio.to_thread(snapshot["_prepare"])
                config.clear()
                config.update(normalize_runtime_config(prepared["config"]))
                config["ABX_RUNTIME"] = "archivebox"
                if self.requested_plugins is not None:
                    _enable_requested_plugins(config, plugins)
                snapshot_service.config = RuntimeConfig(user=GlobalConfig(**config), derived=derived_config)
                await self.bus.emit(MachineEvent(config=config, config_type="user")).now()

                def publish_input():
                    from django.db import close_old_connections

                    try:
                        prepared["_snapshot"].refresh_from_db()
                        prepared["_snapshot"].reconcile_filesystem_links()
                        prepared["_snapshot"].write_index_jsonl(output_dir=output_dir)
                    finally:
                        close_old_connections()

                await asyncio.to_thread(publish_input)

            preparation_handler = self.bus.on(SnapshotEvent, prepare_snapshot)
            snapshot_service = HookSnapshotService(
                self.bus,
                url=snapshot["url"],
                snapshot=abx_snapshot,
                output_dir=output_dir,
                catalog=plugins,
                config=RuntimeConfig(user=GlobalConfig(**config), derived=derived_config),
                snapshot_phase_timeout=snapshot_phase_timeout,
                snapshot_cleanup_phase_timeout=snapshot_phase_timeout,
                abort_requested=self.crawl_is_cancelled,
            )

            async def project_cleanup(event: SnapshotCleanupEvent) -> None:
                if event.snapshot_id == snapshot_id:
                    await self.snapshot_service.on_SnapshotCleanupEvent(event)

            # This serial phase listener must follow the generic cleanup owner:
            # first stop/flush producers, then publish their final metadata. An
            # IO error remains inside abx-dl's handled-failure boundary, before
            # the one terminal fact and its short DB projection.
            cleanup_handler = self.bus.on(SnapshotCleanupEvent, project_cleanup)
            snapshot_event = None
            projected = False
            try:
                snapshot_event = SnapshotEvent(
                    url=snapshot["url"],
                    snapshot_id=snapshot["id"],
                    output_dir=str(output_dir),
                    depth=int(snapshot["depth"]),
                    event_timeout=snapshot_phase_timeout,
                    event_handler_timeout=snapshot_phase_timeout,
                    event_handler_slow_timeout=slow_warning_timeout(snapshot_phase_timeout),
                )
                snapshot_event.event_parent_id = crawl_start_event.event_id
                emitted_snapshot_event = self.bus.emit(snapshot_event)
                await emitted_snapshot_event.now(timeout=snapshot_phase_timeout)
                await emitted_snapshot_event.wait(timeout=snapshot_phase_timeout)
                # A takeover has no terminal fact: the replacement restarts
                # the whole attempt. Waiting for completion here would turn
                # an intentional interruption into a full phase-timeout stall.
                if self.execution_interrupted():
                    return
                completed_snapshot = await self.bus.find(
                    SnapshotCompletedEvent,
                    child_of=emitted_snapshot_event,
                    past=True,
                    future=False,
                )
                if completed_snapshot is None:
                    await emitted_snapshot_event.event_results_list()
                    raise RuntimeError(f"Snapshot {snapshot_id} did not complete")
                await completed_snapshot.wait(timeout=snapshot_phase_timeout)
                await completed_snapshot.event_results_list()
                # A handled preparation failure remains on the phase event for
                # diagnostics. Its awaited terminal error is authoritative; the
                # generic crawl owner reports it after independent work settles.
                if not completed_snapshot.error:
                    await emitted_snapshot_event.event_results_list()
                projected = True
                if self.execution_interrupted():
                    return
                # Explicit plugin maintenance used the same cleanup phase and
                # canonical write. Nothing may rewrite its outputs after the
                # terminal projection has released its lease.
                if snapshot["status"] != "sealed" and self.process_discovered_snapshots_inline:
                    # Cleanup already projected discovery. Re-reading those
                    # remote files here would duplicate work after completion.
                    await self.enqueue_pending_snapshots_from_projection()

            finally:
                self.bus.off(SnapshotEvent, preparation_handler)
                self.bus.off(SnapshotCleanupEvent, cleanup_handler)
                snapshot_service.close()
                # Projection and snapshot cleanup have finished. Historical
                # capture results now live in the database; only active work
                # needs its event ancestry available to the downloader.
                expired = [snapshot_event, user_config_event] if projected and snapshot_event is not None else []
                if projected and derived_config_event is not None:
                    expired.append(derived_config_event)
                if projected and snapshot_event is not None:
                    expired.extend(await self.bus.filter("*", child_of=snapshot_event, past=True, future=False))
                for event in expired:
                    event.event_ttl = 0

    def seal_snapshot_due_to_limit(self, snapshot_id: str) -> None:
        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.select_related("crawl", "crawl__created_by").filter(id=snapshot_id).first()
        if snapshot is None or snapshot.status == Snapshot.StatusChoices.SEALED:
            return
        # Limit stops are runner-owned cancellation decisions, not normal
        # "all ArchiveResults finished" lifecycle seals. Updating the row
        # directly avoids racing a concurrent lifecycle update while
        # concurrent snapshot tasks are stopping because the crawl-wide limit
        # has already been reached.
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
    config_overrides: dict[str, Any] | None = None,
    schedule_all_crawls: bool = False,
    wait_for_resources: bool = True,
) -> None:
    with crawl_lifecycle_lock(crawl_id):
        _run_crawl_locked(
            crawl_id,
            snapshot_ids=snapshot_ids,
            selected_plugins=selected_plugins,
            process_discovered_snapshots_inline=process_discovered_snapshots_inline,
            show_progress=show_progress,
            interactive_interrupts=interactive_interrupts,
            config_overrides=config_overrides,
            schedule_all_crawls=schedule_all_crawls,
            wait_for_resources=wait_for_resources,
        )


def _run_crawl_locked(
    crawl_id: str,
    *,
    snapshot_ids: list[str] | None = None,
    selected_plugins: list[str] | None = None,
    process_discovered_snapshots_inline: bool = True,
    show_progress: bool = True,
    interactive_interrupts: bool = False,
    config_overrides: dict[str, Any] | None = None,
    schedule_all_crawls: bool = False,
    wait_for_resources: bool = True,
) -> None:
    from archivebox.crawls.models import Crawl
    from django.db import close_old_connections

    def run_in_current_thread() -> None:
        close_old_connections()
        try:
            raise_if_shutdown_requested()
            crawl = Crawl.objects.get(id=crawl_id)
            runner = CrawlRunner(
                crawl,
                snapshot_ids=snapshot_ids,
                selected_plugins=selected_plugins,
                process_discovered_snapshots_inline=process_discovered_snapshots_inline,
                show_progress=show_progress,
                interactive_interrupts=interactive_interrupts,
                config_overrides=config_overrides,
                schedule_all_crawls=schedule_all_crawls,
                wait_for_resources=wait_for_resources,
            )
            asyncio.run(runner.run())
            if runner._resource_deferred and wait_for_resources and schedule_all_crawls:
                # The foreground collection loop reconsiders priority after
                # cleanup; a daemon leaves the retry time to its scheduler.
                time.sleep(RESOURCE_RECHECK_SECONDS)
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
    from archivebox.machine.models import Binary, Machine

    binary = await Binary.objects.aget(id=binary_id)
    config = get_config(include_machine=False)
    machine = await sync_to_async(Machine.current, thread_sensitive=True)()
    derived_config = normalize_runtime_config(
        {key: value for key, value in (machine.config or {}).items() if key not in {"SECRET_KEY", "_SECRET_KEY_DB"}},
    )
    config = config.for_crawl()
    config = normalize_runtime_config(config)
    bus = create_bus(name=_bus_name("ArchiveBox_binary", str(binary.id)), total_timeout=1800.0)
    process_service = PersistedProcessService(bus)
    binary_process_service = ArchiveBoxBinaryService(bus)
    BinaryService(bus, lib_dir=Path(config["ABXPKG_LIB_DIR"]))
    TagService(bus)
    MachineService(bus)
    catalog = get_plugin_catalog()
    config["ABX_RUNTIME"] = "archivebox"
    PluginBinaryEnvService(bus, catalog=catalog)
    HookProcessService(bus, emit_jsonl=False, interactive_tty=False, env_filter=filter_crawl_env)
    await bus.emit(MachineEvent(config=config, config_type="user")).now()
    if derived_config:
        await bus.emit(MachineEvent(config=derived_config, config_type="derived")).now()

    request = bus.emit(
        BinaryRequestEvent(
            name=binary.name,
            binproviders=binary.binproviders,
            overrides=binary.overrides or None,
            extra_context={
                "plugin_name": "archivebox",
                "hook_name": "archivebox_binary_run",
                "output_dir": str(binary.output_dir),
                "binary_id": str(binary.id),
                "machine_id": str(binary.machine_id),
            },
        ),
    )
    try:
        await request.now(first_result=True)
    finally:
        await bus.wait_until_idle()
        await binary_process_service.flush_missing_finalizers()
        await process_service.flush_completed()
    resolved = await bus.find(BinaryEvent, child_of=request, past=True, future=False, name=binary.name)
    if isinstance(resolved, BinaryEvent):
        # Resolution can succeed while a DB projection handler fails. Surface
        # that failure instead of returning success with a queued Binary.
        await resolved.event_results_list()


def run_binary(binary_id: str) -> None:
    asyncio.run(_run_binary(binary_id))


def run_snapshot_maintenance(snapshot_id: str, *, output_dir: Path | None = None) -> bool:
    from archivebox.core.models import Snapshot

    snapshot = Snapshot.objects.select_related("crawl", "crawl__created_by").filter(id=snapshot_id).first()
    if snapshot is None:
        return False

    # ArchiveBox owns filesystem and metadata maintenance at Snapshot
    # granularity. ArchiveResult rows are projections and never influence this
    # scheduler decision.
    current_retry_at = snapshot.retry_at
    has_pending_plugin_run = bool((snapshot.config or {}).get("RETRY_PLUGINS"))
    if snapshot.status == Snapshot.StatusChoices.SEALED and has_pending_plugin_run:
        next_retry_at = current_retry_at
    elif snapshot.status in Snapshot.OPEN_STATES:
        next_retry_at = timezone.now()
    else:
        next_retry_at = None
    if snapshot.fs_migration_needed:
        snapshot.migrate_filesystem_to_current_version()
    updated = snapshot.safe_update(
        {"retry_at": next_retry_at},
        extra_filter={
            "status": snapshot.status,
            "retry_at": current_retry_at,
        },
    )
    if not updated:
        return False
    snapshot.write_index_jsonl(output_dir=output_dir)
    return True


def defer_crawl_for_resources(crawl, *, excluded_snapshot_ids=(), required_memory: int | None = None) -> bool:
    """Leave extraction durable; never delay cancellation or final cleanup."""
    from archivebox.core.models import Snapshot

    if crawl.status not in (crawl.StatusChoices.QUEUED, crawl.StatusChoices.STARTED):
        return False
    reason = resource_admission.resource_pressure(
        required_memory=(resource_admission.observed_snapshot_cost or 0) if required_memory is None else required_memory,
    )
    if reason is None:
        return False
    pending = crawl.snapshot_set.filter(status__in=Snapshot.RUNNABLE_STATES).exclude(id__in=excluded_snapshot_ids)
    if crawl.snapshot_set.exists() and not pending.exists():
        return False
    logging.getLogger(__name__).warning("Capture admission deferred for crawl %s: %s", crawl.id, reason)
    now = timezone.now()
    retry_at = now + timedelta(seconds=RESOURCE_RECHECK_SECONDS)
    # Conditional short updates cannot resurrect a concurrent pause/cancel.
    type(crawl).objects.filter(id=crawl.id, status__in=[crawl.StatusChoices.QUEUED, crawl.StatusChoices.STARTED]).update(
        retry_at=retry_at,
        modified_at=now,
    )
    pending.filter(retry_at__lte=now).update(retry_at=retry_at, modified_at=now)
    return True


def run_due_crawl(
    crawl,
    *,
    lock_seconds: int,
    interactive_interrupts: bool = False,
    schedule_all_crawls: bool = False,
    wait_for_resources: bool = True,
) -> bool:
    with crawl_lifecycle_lock(str(crawl.id)):
        return _run_due_crawl_locked(
            crawl,
            lock_seconds=lock_seconds,
            interactive_interrupts=interactive_interrupts,
            schedule_all_crawls=schedule_all_crawls,
            wait_for_resources=wait_for_resources,
        )


def _run_due_crawl_locked(
    crawl,
    *,
    lock_seconds: int,
    interactive_interrupts: bool = False,
    schedule_all_crawls: bool = False,
    wait_for_resources: bool = True,
) -> bool:
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
            status__in=Snapshot.RUNNABLE_STATES,
            retry_at__lte=now,
        ).exists()
        if snapshot_count and due_active_snapshots:
            # Child Snapshot rows own active work. Do not rewrite the parent
            # row unless it is still the same STARTED row we selected; this
            # avoids hot-looping on the parent while child work is ready without
            # resurrecting a user cancellation that sealed the crawl after
            # selection.
            if crawl.status != crawl.StatusChoices.STARTED:
                return False
            return crawl.safe_update(
                {
                    "status": crawl.StatusChoices.STARTED,
                    "retry_at": now + timedelta(seconds=ACTIVE_STATE_LEASE_SECONDS),
                    "modified_at": now,
                },
                refresh=False,
                extra_filter={"status": crawl.StatusChoices.STARTED},
            )
        if snapshot_count and not due_active_snapshots:
            if crawl.is_finished():
                # With no live crawl owner (the lifecycle lock is held here),
                # this retires its aggregate queue row after an interrupted
                # runner already finished every child. It does not reconstruct
                # a lost CrawlCompleted fact or resume/re-execute sealed captures.
                if not crawl.claim_processing_lock(lock_seconds=lock_seconds):
                    return False
                crawl.refresh_from_db()
                crawl.advance_lifecycle()
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
                    status__in=Snapshot.OPEN_STATES,
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
            crawl.advance_lifecycle()
            return True
        _runner_console_line(crawl=crawl)
        run_crawl(
            str(crawl.id),
            process_discovered_snapshots_inline=True,
            interactive_interrupts=interactive_interrupts,
            schedule_all_crawls=schedule_all_crawls,
            wait_for_resources=wait_for_resources,
        )
        return True

    if crawl.status == crawl.StatusChoices.SEALED:
        if not type(crawl).claim_for_worker(crawl, lock_seconds=lock_seconds):
            return False
        _runner_console_line(crawl=crawl, status="SEALED")
        crawl.cleanup_runtime()
        crawl.update_and_requeue(retry_at=None)
        return True

    crawl.update_and_requeue(retry_at=None)
    return True


def run_due_snapshot(
    snapshot,
    *,
    lock_seconds: int,
    interactive_interrupts: bool = False,
    runtime_config=None,
    schedule_all_crawls: bool = False,
    wait_for_resources: bool = True,
) -> bool:
    with crawl_lifecycle_lock(str(snapshot.crawl_id)):
        return _run_due_snapshot_locked(
            snapshot,
            lock_seconds=lock_seconds,
            interactive_interrupts=interactive_interrupts,
            runtime_config=runtime_config,
            schedule_all_crawls=schedule_all_crawls,
            wait_for_resources=wait_for_resources,
        )


def _run_due_snapshot_locked(
    snapshot,
    *,
    lock_seconds: int,
    interactive_interrupts: bool = False,
    runtime_config=None,
    schedule_all_crawls: bool = False,
    wait_for_resources: bool = True,
) -> bool:
    from archivebox.core.models import Snapshot

    try:
        snapshot = Snapshot.objects.get(pk=snapshot.pk)
    except Snapshot.DoesNotExist:
        return False
    parent_reconciled = snapshot.reconcile_parent_lifecycle(lock_seconds=lock_seconds)
    if parent_reconciled is not None:
        if parent_reconciled:
            snapshot.refresh_from_db()
            if snapshot.status == Snapshot.StatusChoices.SEALED and snapshot.fs_migration_needed:
                return run_snapshot_maintenance(str(snapshot.id))
        return parent_reconciled

    if snapshot.is_paused:
        # Paused work never executes out of band. ArchiveResult rows are
        # historical projections and are not rewritten as scheduler state.
        snapshot.restore_paused_scheduler_marker()
        return True
    if snapshot.status == Snapshot.StatusChoices.SEALED:
        if not Snapshot.claim_for_worker(snapshot, lock_seconds=lock_seconds):
            return False
        snapshot.refresh_from_db()
        owned_retry_at = snapshot.retry_at
        snapshot.finalize_completed_upload_results()
        if snapshot.fs_migration_needed:
            snapshot.migrate_filesystem_to_current_version()
        snapshot.refresh_from_db()
        if snapshot.status != Snapshot.StatusChoices.SEALED or snapshot.retry_at != owned_retry_at:
            return True
        retry_plugins = [str(name).strip() for name in (snapshot.config or {}).get("RETRY_PLUGINS", []) if str(name).strip()]
        if retry_plugins:
            _runner_console_line(crawl_id=snapshot.crawl_id, snapshot=snapshot)
            run_crawl(
                str(snapshot.crawl_id),
                snapshot_ids=[str(snapshot.id)],
                selected_plugins=retry_plugins,
                process_discovered_snapshots_inline=False,
                interactive_interrupts=interactive_interrupts,
            )
            return True
        return run_snapshot_maintenance(str(snapshot.id))

    from archivebox.config.common import get_config
    from archivebox.plugins.discovery import get_enabled_plugins

    config = get_config(crawl=snapshot.crawl, persona=snapshot.crawl.resolve_persona())
    configured_plugins = {name.strip().lower() for name in str(config.get("PLUGINS") or "").split(",") if name.strip()}
    chrome_selected = "chrome" in (configured_plugins or set(get_enabled_plugins(config=config)))
    if chrome_selected and str(config.get("CHROME_ISOLATION") or "crawl").lower() == "crawl":
        # The due Snapshot is only the scheduler's admission signal. Running
        # it as an explicit one-snapshot CrawlRunner tears down CrawlSetup after
        # every URL, even though crawl isolation owns one browser for the whole
        # crawl. The crawl lifecycle lock already serializes all of its child
        # work, so let one runner drain the due siblings and discoveries.
        if any(
            process.is_running
            for process in cast(PagedQuerySet, snapshot.process_set.filter(status="running").order_by("pk")).paged_iterator(chunk_size=100)
        ):
            snapshot.update_and_requeue(retry_at=timezone.now() + timedelta(seconds=lock_seconds))
            return True
        if snapshot.fs_migration_needed:
            # Crawl isolation bypasses the per-Snapshot path below, so migrate
            # this admitted Snapshot before the CrawlRunner derives its output
            # directory. Claim the Snapshot as well as holding the lifecycle
            # lock: maintenance-only workers use the Snapshot lease directly.
            if not snapshot.claim_processing_lock(lock_seconds=lock_seconds):
                return False
            snapshot.refresh_from_db()
            claimed_status = snapshot.status
            claimed_retry_at = snapshot.retry_at
            if snapshot.fs_migration_needed:
                snapshot.migrate_filesystem_to_current_version()
            if not snapshot.safe_update(
                {"retry_at": timezone.now()},
                refresh=True,
                extra_filter={"status": claimed_status, "retry_at": claimed_retry_at},
            ):
                return False
        if not snapshot.crawl.claim_processing_lock(lock_seconds=lock_seconds):
            return False
        _runner_console_line(crawl=snapshot.crawl)
        _run_crawl_locked(
            str(snapshot.crawl_id),
            process_discovered_snapshots_inline=True,
            interactive_interrupts=interactive_interrupts,
            schedule_all_crawls=schedule_all_crawls,
            wait_for_resources=wait_for_resources,
        )
        return True

    if not snapshot.claim_processing_lock(lock_seconds=lock_seconds):
        return False
    snapshot.refresh_from_db()
    if any(
        process.is_running
        for process in cast(PagedQuerySet, snapshot.process_set.filter(status="running").order_by("pk")).paged_iterator(chunk_size=100)
    ):
        # The Snapshot lease may have expired while an abx-dl hook process is
        # still alive. Preserve the snapshot-level ownership boundary and do
        # not launch a second sequence; ArchiveResult status is irrelevant.
        snapshot.update_and_requeue(retry_at=timezone.now() + timedelta(seconds=lock_seconds))
        return True
    if snapshot.fs_migration_needed:
        # Migrate before abx-dl writes new hook outputs. The claimed Snapshot
        # lease remains in place and the idempotent migration persists its
        # indexed fs_version marker only after copy/verification/cleanup.
        snapshot.migrate_filesystem_to_current_version()
        snapshot.refresh_from_db()
    if snapshot.status == Snapshot.StatusChoices.QUEUED:
        snapshot.start_processing()
        snapshot.refresh_from_db()
    if snapshot.status != Snapshot.StatusChoices.STARTED:
        return True
    _runner_console_line(crawl_id=snapshot.crawl_id, snapshot=snapshot)
    run_crawl(
        str(snapshot.crawl_id),
        snapshot_ids=[str(snapshot.id)],
        selected_plugins=None,
        process_discovered_snapshots_inline=True,
        interactive_interrupts=interactive_interrupts,
        wait_for_resources=wait_for_resources,
    )
    return True


def run_due_binary(binary, *, lock_seconds: int) -> bool:
    from archivebox.crawls.locks import binary_lifecycle_lock

    with binary_lifecycle_lock(str(binary.id)):
        binary.refresh_from_db()
        if binary.status == binary.StatusChoices.INSTALLED:
            return True
        if not binary.claim_processing_lock(lock_seconds=lock_seconds):
            return False
        run_binary(str(binary.id))
    return True


async def _run_install(plugin_names: list[str] | None = None) -> None:
    from archivebox.config.common import get_config
    from archivebox.machine.models import Machine
    from archivebox.plugins.discovery import get_enabled_plugins

    catalog = get_plugin_catalog()
    config = get_config(include_machine=False)
    machine = await sync_to_async(Machine.current, thread_sensitive=True)()
    derived_config = normalize_runtime_config(
        {key: value for key, value in (machine.config or {}).items() if key not in {"SECRET_KEY", "_SECRET_KEY_DB"}},
    )
    config = config.for_crawl()
    config = normalize_runtime_config(config)
    bus = create_bus(name="ArchiveBox_install", total_timeout=3600.0)
    PersistedProcessService(bus)
    binary_process_service = ArchiveBoxBinaryService(bus)
    BinaryService(bus)
    TagService(bus)
    MachineService(bus)
    live_stream = None
    bus_destroyed = False

    try:
        if plugin_names:
            selected_plugins = catalog.select(plugin_names)
        else:
            selected_plugins = catalog.select(get_enabled_plugins(config=config))
        if not selected_plugins:
            return
        plugins_label = ", ".join(plugin_names) if plugin_names else f"enabled ({len(selected_plugins)} of {len(catalog)} available)"
        install_config = dict(config)
        for plugin in selected_plugins.values():
            if plugin.enabled_key in plugin.config.properties:
                install_config[plugin.enabled_key] = True
        install_config["ABX_RUNTIME"] = "archivebox"
        install_timeout = compute_install_phase_timeout(get_install_plugins(selected_plugins), install_config)
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
                    HookProcessService(bus, emit_jsonl=False, interactive_tty=interactive_tty, env_filter=filter_crawl_env)
                    PluginBinaryEnvService(bus, catalog=selected_plugins)
                    install_snapshot = AbxSnapshot(url="")
                    PluginBinariesService(
                        bus,
                        catalog=selected_plugins,
                        auto_install=True,
                        install_plugins=get_install_plugins(selected_plugins),
                        output_dir=output_dir,
                        snapshot=install_snapshot,
                    )
                    await bus.emit(MachineEvent(config=install_config, config_type="user")).now()
                    if derived_config:
                        await bus.emit(MachineEvent(config=derived_config, config_type="derived")).now()
                    install_event = bus.emit(
                        InstallEvent(
                            url="",
                            snapshot_id=install_snapshot.id,
                            output_dir=str(output_dir),
                            event_timeout=install_timeout,
                            event_handler_slow_timeout=slow_warning_timeout(install_timeout),
                        ),
                    )
                    await install_event.now(timeout=install_timeout)
                    await install_event.wait(timeout=install_timeout)
                    await install_event.event_results_list()
                finally:
                    try:
                        await bus.wait_until_idle()
                        await binary_process_service.flush_missing_finalizers()
                    finally:
                        await bus.destroy(clear=False)
                        bus_destroyed = True
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


# Scheduling policy (run_pending_crawls and _higher_priority_crawl_waiting
# must agree on it, and CrawlRunner applies the within-crawl part):
# Two forces are balanced: adding a URL is a human-guided UI action that must
# respond instantly, while old backlog must still be captured before its
# content goes down or expires.
# - New submissions are admitted newest-first, so something a user just added
#   shows progress immediately instead of waiting behind a huge older import.
# - Everything else drains oldest-first, so the longest-waiting URLs are
#   captured before they disappear.
# - Captures are never resumed: recovery requeues every interrupted STARTED
#   Snapshot as a fresh capture that reruns all hooks (plugins overwrite in
#   place), so it simply takes its FIFO place below. STARTED rows that are due
#   without a restart (an owner lost its lease) still run oldest-first ahead
#   of untouched backlog, and that run is likewise a full capture.
# - Within one crawl, snapshots run FIFO breadth-first by (depth, created_at,
#   pk) so seeds finish before discovered links and ties stay deterministic.
# Accepted tradeoff: a continuous stream of new submissions can delay older
# queued crawls indefinitely.
def _first_due_id(queryset, *, newest_first: bool = False):
    ordering = ("-retry_at", "-created_at") if newest_first else ("retry_at", "created_at")
    # Queue membership comes from retry_at, not status: almost the entire
    # archive can be sealed while only a handful of rows need maintenance.
    # Combining both predicates lets SQLite choose the broad status index and
    # scan/sort archival history on every idle pass (567ms on Cabbage vs 3ms
    # through retry_at). First materialize bounded due IDs using the existing
    # queue index, then apply status/parent filters to those IDs. This also
    # bounds PostgreSQL reads and keeps every cursor closed before a CAS claim.
    due_ids = (
        queryset.model.objects.filter(retry_at__lte=timezone.now())
        .order_by(*ordering)
        .values_list("id", flat=True)
        .paged_iterator(chunk_size=100)
    )
    for candidate_ids in batched(due_ids, 100):
        match = queryset.filter(id__in=candidate_ids).order_by(*ordering).values_list("id", flat=True).first()
        if match is not None:
            return match
    return None


def _next_queued_crawl_snapshot_id(active_snapshots):
    from archivebox.crawls.models import Crawl

    # Avoid paging the entire due snapshot backlog when no new submission
    # exists. A queued parent's lease may be future while its children are due.
    if not Crawl.objects.filter(status=Crawl.StatusChoices.QUEUED).exists():
        return None

    # Newest-first chooses which submission goes next, not its URL order:
    # without crawl isolation the admitted snapshot runs alone, so taking it
    # newest-first would capture an imported list's last line first.
    newest_id = _first_due_id(active_snapshots.filter(crawl__status=Crawl.StatusChoices.QUEUED), newest_first=True)
    if newest_id is None:
        return None
    newest_crawl_id = active_snapshots.filter(id=newest_id).values_list("crawl_id", flat=True).first()
    # Same within-crawl order as CrawlRunner; see _first_due_id.
    return active_snapshots.filter(crawl_id=newest_crawl_id).order_by("depth", "created_at", "pk").values_list("id", flat=True).first()


def _higher_priority_crawl_waiting(crawl_id: str, active_snapshot_ids: list[str]) -> bool:
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    if not Crawl.objects.filter(status=Crawl.StatusChoices.QUEUED).exists():
        return False

    # Only new submissions preempt a running crawl (UI responsiveness). A crawl
    # exists to keep one browser open across a long run of URLs, and each
    # switch costs ~30s of setup, a browser relaunch, and a solo warmup capture
    # (measured on cabbage: ~1 snapshot per 3-6 min instead of ~1/min).
    # Neither older backlog nor another crawl's interrupted captures preempt:
    # restarts leave several of those, and yielding to each one re-launched
    # Chrome after every single snapshot. They resume oldest-first when the
    # outer scheduler next picks work (passes in run_pending_crawls).
    # Only the winning crawl matters here, so pass 1 can skip the within-crawl
    # pick _next_queued_crawl_snapshot_id makes. Owned captures finish in this
    # runner; an expired lease must not make one look like a new admission.
    active_snapshots = Snapshot.objects.filter(
        retry_at__lte=timezone.now(),
        crawl__status__in=Crawl.RUNNABLE_STATES,
        status__in=Snapshot.RUNNABLE_STATES,
    ).exclude(id__in=active_snapshot_ids)
    for queryset, newest_first in (
        (active_snapshots.filter(crawl__status=Crawl.StatusChoices.QUEUED), True),
        (Crawl.objects.filter(retry_at__lte=timezone.now(), status=Crawl.StatusChoices.QUEUED), True),
    ):
        candidate_id = _first_due_id(queryset, newest_first=newest_first)
        if candidate_id is not None:
            if queryset.model is Crawl:
                return str(candidate_id) != crawl_id
            next_crawl_id = Snapshot.objects.filter(id=candidate_id).values_list("crawl_id", flat=True).first()
            return next_crawl_id is not None and str(next_crawl_id) != crawl_id
    return False


def _run_due_crawl_status(
    status: str,
    *,
    crawl_id: str | None,
    lock_seconds: int,
    interactive_interrupts: bool,
    newest_first: bool = False,
    wait_for_resources: bool = True,
) -> bool:
    from archivebox.crawls.models import Crawl

    due_crawls = Crawl.objects.filter(
        retry_at__lte=timezone.now(),
        status=status,
    )
    if crawl_id:
        due_crawls = due_crawls.filter(id=crawl_id)
    due_crawl_id = _first_due_id(due_crawls, newest_first=newest_first)
    if due_crawl_id is None:
        return False
    due_crawl = Crawl.objects.filter(id=due_crawl_id).first()
    if due_crawl is None:
        return True
    return run_due_crawl(
        due_crawl,
        lock_seconds=lock_seconds,
        interactive_interrupts=interactive_interrupts,
        schedule_all_crawls=crawl_id is None,
        wait_for_resources=wait_for_resources,
    )


def _run_due_snapshot_query(
    queryset,
    *,
    lock_seconds: int,
    interactive_interrupts: bool,
    runtime_config,
    schedule_all_crawls: bool = False,
    wait_for_resources: bool = True,
) -> bool:
    due_snapshot_id = _first_due_id(queryset)
    return _run_due_snapshot_id(
        due_snapshot_id,
        lock_seconds=lock_seconds,
        interactive_interrupts=interactive_interrupts,
        runtime_config=runtime_config,
        schedule_all_crawls=schedule_all_crawls,
        wait_for_resources=wait_for_resources,
    )


def _run_due_snapshot_id(
    snapshot_id,
    *,
    lock_seconds: int,
    interactive_interrupts: bool,
    runtime_config,
    schedule_all_crawls: bool = False,
    wait_for_resources: bool = True,
) -> bool:
    from archivebox.core.models import Snapshot

    due_snapshot_id = snapshot_id
    if due_snapshot_id is None:
        return False
    due_snapshot = Snapshot.objects.filter(id=due_snapshot_id).first()
    if due_snapshot is None:
        return True
    # A lost/busy claim is not progress. Let the scheduler try other work and
    # reach its idle wait instead of spinning on the same due child forever.
    return run_due_snapshot(
        due_snapshot,
        lock_seconds=lock_seconds,
        interactive_interrupts=interactive_interrupts,
        runtime_config=runtime_config,
        schedule_all_crawls=schedule_all_crawls,
        wait_for_resources=wait_for_resources,
    )


def _run_due_binary() -> bool:
    from archivebox.machine.models import Binary

    due_binary_id = _first_due_id(
        Binary.objects.filter(retry_at__lte=timezone.now()).exclude(status=Binary.StatusChoices.INSTALLED),
    )
    if due_binary_id is None:
        return False
    due_binary = Binary.objects.filter(id=due_binary_id).first()
    if due_binary is None:
        return True
    return run_due_binary(due_binary, lock_seconds=60)


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
    from archivebox.machine.models import Process

    crawl_claim_lock_seconds = 10
    runtime_config = get_config()
    last_recovery_at = 0.0
    last_retention_at = 0.0
    last_retention_repair_at = 0.0
    retention_backfill_cursors: dict = {}
    deletion_thread: threading.Thread | None = None
    last_analyze_at = 0.0
    analyze_queue: list[str] | None = None
    analyze_sweep_started_at = 0.0
    orchestrator_started_at = time.monotonic()

    def delete_in_background() -> None:
        from django.db import connections

        try:
            Snapshot.delete_requested(batch_size=100, drain=True)
        finally:
            connections.close_all()

    while True:
        raise_if_shutdown_requested()
        now_monotonic = time.monotonic()
        if crawl_id is None and (daemon or not maintenance_only):
            from archivebox.importers.service import tick as tick_importers

            if tick_importers(daemon=daemon):
                continue
        if crawl_id is None and now_monotonic - last_retention_at >= (60.0 if daemon else 1.0):
            if daemon:
                # At most one job can be doing filesystem I/O. A stuck mount
                # must not block capture scheduling or runner shutdown; rows
                # remain pending until cleanup succeeds, including on restart.
                if (deletion_thread is None or not deletion_thread.is_alive()) and Snapshot.objects.filter(
                    status=Snapshot.DELETING_STATE,
                ).exists():
                    deletion_thread = threading.Thread(target=delete_in_background, name="snapshot-delete", daemon=True)
                    deletion_thread.start()
            else:
                Snapshot.delete_requested(batch_size=100)
            for model in (ArchiveResult, Snapshot, Crawl, Process):
                # Keep the tight scheduler loop anchored on indexed delete_at
                # columns only. Backfilling missing delete_at values has to read
                # config JSON for models whose retention policy is scoped to a
                # Crawl/Snapshot/Process. That repair is still required for
                # correctness, but it belongs in the idle maintenance block
                # below, not ahead of every claim attempt.
                model.delete_expired(batch_size=100, backfill_missing=False)
            last_retention_at = now_monotonic

        if daemon and crawl_id is None:
            now = timezone.now()
            for schedule in CrawlSchedule.objects.filter(is_enabled=True).select_related("template", "template__created_by"):
                if schedule.is_due(now):
                    schedule.dispatch(queued_at=now)

        if maintenance_only:
            # Filesystem migration is independent of lifecycle status; do not
            # tick queued snapshots or start their extraction work here.
            filesystem_snapshot = (
                Snapshot.objects.filter(retry_at__lte=timezone.now())
                .exclude(fs_version=Snapshot._fs_current_version())
                .order_by("retry_at", "created_at")
                .first()
            )
            if filesystem_snapshot and Snapshot.claim_for_worker(filesystem_snapshot, lock_seconds=60):
                if run_snapshot_maintenance(str(filesystem_snapshot.id)):
                    continue

        if not maintenance_only:
            active_snapshots = Snapshot.objects.filter(
                retry_at__lte=timezone.now(),
                crawl__status__in=Crawl.RUNNABLE_STATES,
                status__in=Snapshot.RUNNABLE_STATES,
            )
            if crawl_id:
                active_snapshots = active_snapshots.filter(crawl_id=crawl_id)
            # New submissions newest-first so they show progress before old
            # backlog (policy above _first_due_id). Keep this pass order in
            # sync with _higher_priority_crawl_waiting.
            if _run_due_snapshot_id(
                _next_queued_crawl_snapshot_id(active_snapshots),
                lock_seconds=60,
                interactive_interrupts=interactive_interrupts,
                wait_for_resources=not daemon,
                runtime_config=runtime_config,
                schedule_all_crawls=crawl_id is None,
            ):
                continue

            # Same newest-first admission for queued crawls that have no due
            # snapshot yet (policy above _first_due_id).
            if _run_due_crawl_status(
                Crawl.StatusChoices.QUEUED,
                crawl_id=crawl_id,
                lock_seconds=crawl_claim_lock_seconds,
                interactive_interrupts=interactive_interrupts,
                wait_for_resources=not daemon,
                newest_first=True,
            ):
                continue

            # Started work resumes oldest-first before untouched backlog
            # (policy above _first_due_id).
            if any(
                _run_due_snapshot_query(
                    due_snapshots,
                    lock_seconds=60,
                    interactive_interrupts=interactive_interrupts,
                    wait_for_resources=not daemon,
                    runtime_config=runtime_config,
                    schedule_all_crawls=crawl_id is None,
                )
                for due_snapshots in (active_snapshots.filter(status=Snapshot.StatusChoices.STARTED), active_snapshots)
            ):
                continue

        if not maintenance_only:
            if _run_due_crawl_status(
                Crawl.StatusChoices.STARTED,
                crawl_id=crawl_id,
                lock_seconds=crawl_claim_lock_seconds,
                interactive_interrupts=interactive_interrupts,
                wait_for_resources=not daemon,
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
                wait_for_resources=not daemon,
                runtime_config=runtime_config,
            ):
                continue

        if not maintenance_only:
            pausing_snapshots = Snapshot.objects.filter(
                retry_at__lte=timezone.now(),
                crawl__status=Crawl.StatusChoices.PAUSED,
                status__in=Snapshot.RUNNABLE_STATES,
            )
            if crawl_id:
                pausing_snapshots = pausing_snapshots.filter(crawl_id=crawl_id)
            if _run_due_snapshot_query(
                pausing_snapshots,
                lock_seconds=60,
                interactive_interrupts=interactive_interrupts,
                wait_for_resources=not daemon,
                runtime_config=runtime_config,
            ):
                continue

        # Final active-state fallback uses only the retry_at scheduler index and
        # selects an id first. Keep final SEALED rows out of this broad path so
        # large filesystem/index backfills cannot starve newly queued crawls.
        if not maintenance_only:
            due_snapshots = Snapshot.objects.filter(
                retry_at__lte=timezone.now(),
                status__in=Snapshot.OPEN_STATES,
            )
            if crawl_id:
                due_snapshots = due_snapshots.filter(crawl_id=crawl_id)
            if _run_due_snapshot_query(
                due_snapshots,
                lock_seconds=60,
                interactive_interrupts=interactive_interrupts,
                wait_for_resources=not daemon,
                runtime_config=runtime_config,
            ):
                continue

        if not maintenance_only:
            # Final snapshots can still have an explicit filesystem/index-json
            # maintenance tick. Search extraction is invoked directly by the
            # update path and never enters this scheduler through ArchiveResult.
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
                wait_for_resources=not daemon,
                runtime_config=runtime_config,
            ):
                continue

        if not maintenance_only:
            if _run_due_crawl_status(
                Crawl.StatusChoices.SEALED,
                crawl_id=crawl_id,
                lock_seconds=crawl_claim_lock_seconds,
                interactive_interrupts=interactive_interrupts,
                wait_for_resources=not daemon,
            ):
                continue

        if crawl_id is None and not maintenance_only:
            if _run_due_binary():
                continue

        now_monotonic = time.monotonic()
        if crawl_id is None and now_monotonic - last_retention_repair_at >= (60.0 if daemon else 0.0):
            for model in (ArchiveResult, Snapshot, Crawl, Process):
                # No runnable work was found on this scheduler pass. This is
                # the bounded repair point for missing retention deadlines,
                # including ArchiveResult rows intentionally saved without
                # delete_at in the plugin-result hot path. Running it here keeps
                # DELETE_AFTER resolution fresh without making every hook event
                # load parent Snapshot/Crawl config.
                model.delete_expired(batch_size=100, backfill_missing=True, backfill_cursors=retention_backfill_cursors)
            last_retention_repair_at = now_monotonic

        if daemon:
            now_monotonic = time.monotonic()
            if now_monotonic - last_recovery_at >= 30.0:
                from archivebox.core.recovery_util import recover_orchestrator_state

                recover_orchestrator_state()
                last_recovery_at = now_monotonic
            # SQLite query plans degrade as the snapshot/archiveresult tables grow
            # past their last ANALYZE — stale stats make the optimizer start large
            # joins from auth_user/crawl instead of using the url index, blowing the
            # snapshot detail page out to ~500ms. Refresh stats at most once per
            # 24hr while the queue is idle, and only after the orchestrator has
            # been alive for at least an hour so short server boots / one-off work
            # never pay the cost. Each idle tick samples a bounded number of
            # index entries for one table; never scan the full history while
            # holding ANALYZE's write transaction. Optional stats refresh must
            # not prevent queued captures.
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
