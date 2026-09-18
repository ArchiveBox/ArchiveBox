from __future__ import annotations
import asyncio
import sys
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from asgiref.sync import sync_to_async
from abxpkg.binary_service import BinaryRequestEvent, BinaryService
from abx_dl.events import (
    InstallEvent,
    MachineEvent,
    slow_warning_timeout,
)
from abx_dl.models import Snapshot as AbxSnapshot
from abx_dl.orchestrator import (
    compute_install_phase_timeout,
    create_bus,
    get_install_plugins,
)
from abx_dl.services.binary_service import PluginBinaryEnvService
from abx_dl.services import PluginBinariesService
from abx_dl.services.process_service import ProcessService as HookProcessService
from abx_dl.cli import LiveBusUI
from archivebox.config.common import (
    normalize_runtime_config,
)
from archivebox.plugins.discovery import get_plugin_catalog
from ..binary_service import ArchiveBoxBinaryService
from ..machine_service import MachineService
from ..process_service import ProcessService as PersistedProcessService
from ..tag_service import TagService

from .crawl import _bus_name
from .console import _count_selected_hooks, create_console


async def _run_binary(binary_id: str) -> None:
    from archivebox.config.common import get_config
    from archivebox.machine.models import Binary, Machine

    binary = await Binary.objects.aget(id=binary_id)
    config = get_config(include_machine=False)
    machine = await sync_to_async(Machine.current, thread_sensitive=True)()
    derived_config = normalize_runtime_config(machine.config)
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
    HookProcessService(bus, emit_jsonl=False, interactive_tty=False)
    await bus.emit(MachineEvent(config=config, config_type="user")).now()
    if derived_config:
        await bus.emit(MachineEvent(config=derived_config, config_type="derived")).now()

    try:
        await bus.emit(
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
        ).now(first_result=True)
    finally:
        await bus.wait_until_idle()
        await binary_process_service.flush_missing_finalizers()
        await process_service.flush_completed()


def run_binary(binary_id: str) -> None:
    asyncio.run(_run_binary(binary_id))


async def _run_install(plugin_names: list[str] | None = None) -> None:
    from archivebox.config.common import get_config
    from archivebox.machine.models import Machine
    from archivebox.plugins.discovery import get_enabled_plugins

    catalog = get_plugin_catalog()
    config = get_config(include_machine=False)
    machine = await sync_to_async(Machine.current, thread_sensitive=True)()
    derived_config = normalize_runtime_config(machine.config)
    config = config.for_crawl()
    config = normalize_runtime_config(config)
    bus = create_bus(name="ArchiveBox_install", total_timeout=3600.0)
    PersistedProcessService(bus)
    ArchiveBoxBinaryService(bus)
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
            ui_console, live_stream, interactive_tty = create_console()

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
                    HookProcessService(bus, emit_jsonl=False, interactive_tty=interactive_tty)
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
