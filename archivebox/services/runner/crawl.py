from __future__ import annotations
import asyncio
import contextvars
import os
import signal
import sys
import threading
import time
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from typing import Any
from asgiref.sync import sync_to_async
from django.core.exceptions import ValidationError
from django.utils import timezone
from abxpkg.binary_service import BinaryService
from abx_dl.events import (
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
from abx_dl.limits import CrawlLimitState
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
from abx_dl.services import PluginBinariesService
from abx_dl.services.process_service import ProcessService as HookProcessService
from abx_dl.services.snapshot_service import SnapshotService as HookSnapshotService
from abx_dl.cli import LiveBusUI
from abxbus import BaseEvent
from abxbus.event_bus import EventBus, get_current_event, in_handler_context
from abxbus.event_handler import EventHandlerAbortedError, EventHandlerCancelledError
from archivebox.config.common import (
    ArchiveBoxBaseConfig,
    normalize_runtime_config,
    _plugin_enabled_config_keys,
)
from archivebox.core.shutdown_util import foreground_shutdown_signals
from archivebox.plugins.discovery import get_plugin_catalog
from archivebox.search.sonic_daemon import register_sonic_daemon_event_handler
from archivebox.workers.models import ACTIVE_STATE_LEASE_SECONDS
from archivebox.crawls.locks import crawl_lifecycle_lock
from ..archive_result_service import ArchiveResultService
from ..binary_service import ArchiveBoxBinaryService, project_abxpkg_derived_cache_to_db
from ..crawl_service import CrawlService
from ..machine_service import MachineService
from ..process_service import ProcessService as PersistedProcessService
from ..snapshot_service import SnapshotService, project_discovered_snapshots
from ..tag_service import TagService

from .console import _count_selected_hooks, create_console
from .maintenance import run_snapshot_maintenance


async def _run_event_now(event, timeout: float | None = None):
    await event.now(timeout=timeout)
    await event.wait(timeout=timeout)
    await event.event_results_list()
    return event


def _bus_name(prefix: str, identifier: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in identifier)
    return f"{prefix}_{normalized}"


def _enable_requested_plugins(config: dict[str, Any], plugins: PluginCatalog) -> None:
    for plugin in plugins.values():
        if plugin.enabled_key in plugin.config.properties:
            config[plugin.enabled_key] = True


def _is_nonfatal_setup_hook(plugin_name: str, hook_name: str) -> bool:
    return plugin_name == "chrome" and hook_name.endswith("_chrome_kill_zombies")


def _runner_task_context() -> contextvars.Context:
    context = contextvars.copy_context()
    context.run(EventBus.current_event_context.set, None)
    context.run(EventBus.current_handler_id_context.set, None)
    context.run(EventBus.current_eventbus_context.set, None)
    return context


def _is_external_task_cancelled(error: asyncio.CancelledError) -> bool:
    return not isinstance(error, (EventHandlerAbortedError, EventHandlerCancelledError))


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
    ):
        self.crawl = crawl
        self.bus = create_bus(name=_bus_name("ArchiveBox", str(crawl.id)), total_timeout=3600.0)
        self.catalog = get_plugin_catalog()
        HookProcessService(self.bus, emit_jsonl=False, interactive_tty=interactive_interrupts)
        register_sonic_daemon_event_handler(self.bus)
        PersistedProcessService(self.bus)
        ArchiveBoxBinaryService(self.bus)
        BinaryService(self.bus)
        TagService(self.bus)
        CrawlService(self.bus, crawl_id=str(crawl.id))
        MachineService(self.bus)
        self.process_discovered_snapshots_inline = process_discovered_snapshots_inline
        self.show_progress = show_progress
        self.interactive_interrupts = interactive_interrupts
        self.config_overrides = dict(config_overrides or {})

        self.snapshot_service = SnapshotService(
            self.bus,
            crawl_id=str(crawl.id),
        )
        HookArchiveResultService(self.bus, emit_jsonl=False)
        ArchiveResultService(self.bus)
        self.requested_plugins = selected_plugins
        self.selected_plugins = selected_plugins
        self.initial_snapshot_ids = snapshot_ids
        self.snapshot_tasks: dict[str, asyncio.Task[None]] = {}
        self.snapshot_semaphore = asyncio.Semaphore(1)
        self.max_concurrent_snapshots = 1
        self.persona = None
        self.base_config: ArchiveBoxBaseConfig | dict[str, Any] = {}
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
        if os.environ.get("ARCHIVEBOX_RUNNER_DAEMON") == "1":
            # The daemon runner is owned by supervisord, not by the interactive
            # CLI foreground flow. A direct signal to this child should be short
            # and unambiguous: exit non-zero immediately so supervisord restarts
            # the runner, while the parent server and supervisord stay alive.
            os._exit(128 + int(_sig))
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
            if not await self.crawl_is_cancelled():
                continue
            abort_event = parent_event.emit(CrawlAbortEvent())
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
        try:
            first_signal_message = (
                "\n[🛑] Got {signal_name}, aborting the active hook...\n"
                if self.interactive_interrupts
                else "\n[🛑] Got {signal_name}, stopping gracefully...\n"
            )
            self._run_task = asyncio.current_task()
            # Do not raise KeyboardInterrupt directly from an OS signal while
            # the asyncio loop is active. Python can inject it into whichever
            # task is currently running, which produces noisy "Task exception
            # was never retrieved" logs from unrelated abxbus housekeeping
            # tasks. _request_abort_from_signal() cancels the runner task
            # cooperatively instead; repeated signals still hard-exit in the
            # shared foreground signal handler.
            with foreground_shutdown_signals(
                first_signal_message=first_signal_message,
                on_signal=self._request_abort_from_signal,
                raise_on_first_signal=False,
            ):
                snapshot_ids = await sync_to_async(self.load_run_state, thread_sensitive=True)()
                max_concurrent_snapshots = max(1, int(self.base_config.get("CRAWL_MAX_CONCURRENT_SNAPSHOTS", 1)))
                self.max_concurrent_snapshots = max_concurrent_snapshots
                self.snapshot_semaphore = asyncio.Semaphore(max_concurrent_snapshots)
                live_ui = self._create_live_ui()
                with live_ui if live_ui is not None else nullcontext():
                    try:
                        if snapshot_ids:
                            root_snapshot_id = snapshot_ids[0]
                            await self.run_crawl(root_snapshot_id, snapshot_ids)
                    finally:
                        self._run_task = None
                        await self.stop_snapshot_tasks()
                        try:
                            await self.bus.wait_until_idle(timeout=1.0 if self._skip_wait_until_idle else 30.0)
                        except TimeoutError:
                            pass
                        finally:
                            await self.bus.destroy(clear=False)
                            bus_destroyed = True
        finally:
            if not bus_destroyed:
                self._run_task = None
                await self.stop_snapshot_tasks()
                await self.bus.destroy(clear=False)
            if self._live_stream is not None:
                try:
                    self._live_stream.close()
                except Exception:
                    pass
                self._live_stream = None
            await sync_to_async(project_abxpkg_derived_cache_to_db, thread_sensitive=True)(self.base_config.get("ABXPKG_LIB_DIR"))
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

    async def wait_for_snapshot_tasks(self, *, enqueue_projected: bool = True) -> None:
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
                if enqueue_projected:
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
            if not stop_scheduling and enqueue_projected:
                await self.enqueue_pending_snapshots_from_projection()

    async def heartbeat_active_leases(self) -> None:
        # These are resumable work-item leases, not orchestrator-election
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

        if not isinstance(get_current_event(), CrawlStartEvent):
            return
        if await self.crawl_is_cancelled():
            return
        if await self.crawl_is_paused() and not self.allow_maintenance_on_inactive_crawl:
            return

        await sync_to_async(self.crawl.refresh_from_db, thread_sensitive=True)()
        config = await sync_to_async(lambda: get_config(crawl=self.crawl), thread_sensitive=True)()
        self.max_concurrent_snapshots = max(1, int(config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"]))

        active_snapshot_ids = [snapshot_id for snapshot_id, task in self.snapshot_tasks.items() if not task.done()]
        available_slots = max(0, self.max_concurrent_snapshots - len(active_snapshot_ids))
        if available_slots <= 0:
            return
        pending_snapshot_ids = await sync_to_async(
            lambda: list(
                self.crawl.snapshot_set.filter(status__in=Snapshot.RUNNABLE_STATES)
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
        from archivebox.plugins.discovery import get_enabled_plugins
        from archivebox.machine.models import Machine, NetworkInterface, Process

        self.primary_url = self.crawl.get_urls_list()[0] if self.crawl.get_urls_list() else ""
        current_iface = NetworkInterface.current(refresh=not self.allow_maintenance_on_inactive_crawl)
        current_process = Process.current()
        if current_process.iface_id != current_iface.id or current_process.machine_id != current_iface.machine_id:
            current_process.iface = current_iface
            current_process.machine = current_iface.machine
            current_process.save(update_fields=["iface", "machine", "modified_at"])
        self.persona = self.crawl.resolve_persona()
        self.base_config = get_config(crawl=self.crawl, overrides=self.config_overrides)
        self.derived_config = dict(Machine.current().config or {})
        self.crawl_output_dir = str(self.crawl.output_dir)
        if self.persona:
            self.base_config.update(
                self.persona.prepare_runtime_for_crawl(
                    self.crawl,
                    chrome_binary=self.base_config["CHROME_BINARY"],
                ),
            )
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
            return [str(snapshot_id) for snapshot_id in self.initial_snapshot_ids]
        pending_snapshots = list(
            self.crawl.snapshot_set.filter(status__in=Snapshot.RUNNABLE_STATES)
            .filter(retry_at__lte=timezone.now())
            .order_by("depth", "created_at"),
        )
        if pending_snapshots:
            return [str(snapshot.id) for snapshot in pending_snapshots]
        if self.crawl.snapshot_set.exclude(status__in=[Snapshot.StatusChoices.SEALED, Snapshot.StatusChoices.PAUSED]).exists():
            return []
        created = self.create_initial_snapshots()
        snapshots = created or list(self.crawl.snapshot_set.filter(depth__in=[0, 1]).order_by("depth", "created_at"))
        return [str(snapshot.id) for snapshot in snapshots]

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
        if crawl.is_finished():
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
        ui_console, self._live_stream, interactive_tty = create_console()
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

    def load_snapshot_payload(self, snapshot_id: str) -> dict[str, Any]:
        from archivebox.config.common import get_config
        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.select_related("crawl", "crawl__created_by").get(id=snapshot_id)
        self.crawl = snapshot.crawl
        self.persona = snapshot.crawl.resolve_persona()
        self.base_config = get_config(crawl=snapshot.crawl, persona=self.persona, overrides=self.config_overrides)
        self.crawl_output_dir = str(snapshot.crawl.output_dir)
        runtime_chrome_overrides = {}
        if self.persona:
            if str(self.base_config.get("CHROME_ISOLATION") or "crawl").lower() == "snapshot":
                runtime_chrome_overrides.update(
                    self.persona.prepare_runtime_for_snapshot(
                        snapshot,
                        chrome_binary=self.base_config["CHROME_BINARY"],
                    ),
                )
            else:
                crawl_downloads_dir = self.persona.runtime_downloads_dir_for_crawl(snapshot.crawl)
                crawl_downloads_dir.mkdir(parents=True, exist_ok=True)
                runtime_chrome_overrides.update(
                    {
                        "PERSONAS_DIR": str(self.persona.runtime_root_for_crawl(snapshot.crawl).parent),
                        "ACTIVE_PERSONA": self.persona.name,
                    },
                )
        snapshot_output_dir = str(snapshot.output_dir)
        tags = snapshot.tags_str()
        config = self.base_config.for_crawl_runtime(
            crawl=snapshot.crawl,
            snapshot=snapshot,
            persona=self.persona,
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

    async def enqueue_discovered_snapshots_from_outputs(self, snapshot_payload: dict[str, Any]) -> None:
        await sync_to_async(project_discovered_snapshots, thread_sensitive=True)(snapshot_payload["id"])
        if self.process_discovered_snapshots_inline and isinstance(get_current_event(), CrawlStartEvent):
            await self.enqueue_pending_snapshots_from_projection()

    async def run_crawl(self, root_snapshot_id: str, snapshot_ids: list[str]) -> None:
        snapshot = await sync_to_async(self.load_snapshot_payload, thread_sensitive=True)(root_snapshot_id)
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
        snapshot_phase_timeout = compute_phase_timeout(plugins.hooks("Snapshot"), config) + 120.0
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

        async def on_archivebox_CrawlStartEvent(event: CrawlStartEvent) -> None:
            if event.event_id != self.root_crawl_start_event_id:
                return
            if self.initial_snapshot_ids is not None:
                remaining_snapshot_ids = iter(snapshot_ids)
                while True:
                    batch = list(zip(range(self.max_concurrent_snapshots), remaining_snapshot_ids, strict=False))
                    if not batch:
                        return
                    for _slot, snapshot_id in batch:
                        if await self.crawl_is_cancelled():
                            return
                        if await self.crawl_is_paused() and not self.allow_maintenance_on_inactive_crawl:
                            return
                        await self.enqueue_snapshot(snapshot_id)
                    await self.wait_for_snapshot_tasks(enqueue_projected=False)
            else:
                for snapshot_id in snapshot_ids[: self.max_concurrent_snapshots]:
                    if await self.crawl_is_cancelled():
                        break
                    if await self.crawl_is_paused():
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
                            event_timeout=all_snapshots_phase_timeout,
                            event_handler_timeout=all_snapshots_phase_timeout + 30.0,
                            event_handler_slow_timeout=slow_warning_timeout(all_snapshots_phase_timeout),
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
                    # Cleanup owns ProcessKillEvent emission for crawl-scoped
                    # setup hooks. Even during OS-signal shutdown we must drive
                    # it synchronously before bus teardown; otherwise daemon/bg
                    # setup hooks can outlive the foreground runner that
                    # launched them. _run_event_now() is already bounded by the
                    # crawl setup timeout and cleanup handlers provide their own
                    # hook-level grace periods.
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
                if _is_nonfatal_setup_hook(plugin.name, hook.name):
                    continue
                raise RuntimeError(f"Crawl setup hook {plugin.name}:{hook.name} failed")

    async def run_snapshot(self, snapshot_id: str, crawl_start_event: CrawlStartEvent | None = None) -> None:
        async with self.snapshot_semaphore:
            crawl_start_event = crawl_start_event or get_current_event()
            if not isinstance(crawl_start_event, CrawlStartEvent):
                raise RuntimeError("Snapshot events must be emitted from a CrawlStartEvent handler")
            snapshot = await sync_to_async(self.load_snapshot_payload, thread_sensitive=True)(snapshot_id)
            try:
                snapshot["_snapshot"].validate_url_for_archiving(config=snapshot["config"])
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
            if snapshot["depth"] > 0 and CrawlLimitState.from_config(snapshot["config"]).get_stop_reason() in (
                "crawl_max_size",
                "crawl_timeout",
            ):
                await sync_to_async(self.seal_snapshot_due_to_limit, thread_sensitive=True)(snapshot_id)
                return
            derived_config = normalize_runtime_config(self.derived_config)
            output_dir = Path(snapshot["output_dir"])
            # Hooks read snapshot metadata from the manifest; EXTRA_CONTEXT is
            # only an opaque record-correlation envelope, never a data input.
            await sync_to_async(snapshot["_snapshot"].write_index_jsonl, thread_sensitive=True)(output_dir=output_dir)
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
            snapshot_phase_timeout = compute_phase_timeout(plugins.hooks("Snapshot"), config) + 120.0
            user_config_event = MachineEvent(config=config, config_type="user")
            user_config_event.event_parent_id = crawl_start_event.event_id
            await self.bus.emit(user_config_event).now()
            if derived_config:
                derived_config_event = MachineEvent(config=derived_config, config_type="derived")
                derived_config_event.event_parent_id = crawl_start_event.event_id
                await self.bus.emit(derived_config_event).now()
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
                if snapshot["status"] == "sealed":
                    await sync_to_async(run_snapshot_maintenance, thread_sensitive=True)(snapshot_id, output_dir=output_dir)
                    return
                await self.enqueue_discovered_snapshots_from_outputs(snapshot)

                def _seal_when_last_snapshot_finished() -> None:
                    # Re-read immediately before the idempotent conditional
                    # update so concurrent last-snapshot completions are safe.
                    crawl = self.crawl
                    crawl.refresh_from_db(fields=["status"])
                    if crawl.status != crawl.StatusChoices.STARTED:
                        return
                    if crawl.snapshot_set.filter(
                        status__in=crawl.snapshot_set.model.OPEN_STATES,
                    ).exists():
                        return
                    crawl.seal()

                await sync_to_async(_seal_when_last_snapshot_finished, thread_sensitive=True)()
            finally:
                snapshot_service.close()

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
                    config_overrides=config_overrides,
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
