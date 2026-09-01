"""ArchiveBox adapters around the framework-free abx-dl plugin runtime.

Discovery and execution are owned by abx-dl. ArchiveBox keeps only the small
Django projection adapter and its application-specific URL-output reader.
"""

from __future__ import annotations

__package__ = "archivebox.plugins"

import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeGuard, runtime_checkable

from asgiref.sync import async_to_sync

from abx_dl.execution import execute_hook
from abx_dl.models import Hook, parse_hook_filename

from archivebox.config.constants import CONSTANTS
from archivebox.config.version import VERSION
from archivebox.misc.util import fix_url_from_markdown, sanitize_extracted_url
from archivebox.plugins.discovery import ConfigLookup, get_enabled_plugins, get_plugin_catalog, get_plugin_special_config

if TYPE_CHECKING:
    from archivebox.machine.models import Process


@runtime_checkable
class ConfigDump(Protocol):
    def as_dict(self) -> dict[str, Any]: ...


def _has_config_dump(config: object) -> TypeGuard[ConfigDump]:
    return isinstance(config, ConfigDump)


def _config_to_overrides(config: ConfigLookup | Mapping[str, Any] | None) -> dict[str, Any]:
    if config is None:
        return {}
    if _has_config_dump(config):
        return dict(config.as_dict())
    return dict(config.items())


def is_background_hook(hook_name: str) -> bool:
    parsed = parse_hook_filename(Path(hook_name).name)
    return bool(parsed and parsed[2])


def normalize_hook_event_name(event_name: str) -> str | None:
    normalized = str(event_name or "").strip()
    if not normalized:
        return None
    return normalized.removesuffix("Event") or None


def discover_hooks(
    event_name: str,
    filter_disabled: bool = True,
    config: ConfigLookup | None = None,
    **config_kwargs: Any,
) -> list[Path]:
    """Return the exact catalog hooks used by abx-dl, in execution order."""
    normalized = normalize_hook_event_name(event_name)
    if not normalized or normalized == "BinaryRequest":
        return []
    names = None
    if filter_disabled:
        if config is None:
            from archivebox.config.common import get_config

            config = get_config(**config_kwargs)
        names = get_enabled_plugins(config=config)
    return [hook.path for _plugin, hook in get_plugin_catalog().hooks(normalized, names=names)]


def _catalog_hook(script: Path) -> Hook:
    script = script.resolve()
    for plugin in get_plugin_catalog().values():
        for hook in plugin.hooks:
            if hook.path.resolve() == script:
                return hook
    parsed = parse_hook_filename(script.name)
    if parsed is None:
        raise ValueError(f"Not a valid plugin hook filename: {script.name}")
    event, order, is_background = parsed
    return Hook(
        name=script.name,
        event=event,
        plugin_name=script.parent.name,
        path=script,
        order=order,
        is_background=is_background,
    )


def _hook_environment(config: ConfigLookup | Mapping[str, Any] | None, **config_scope: Any) -> tuple[dict[str, str], Any]:
    from archivebox.config.common import (
        ArchiveBoxConfig,
        _archivebox_config_input_names,
        get_config,
        normalize_runtime_config,
    )

    overrides = _config_to_overrides(config)
    resolved = get_config(overrides=overrides, **config_scope)
    runtime = normalize_runtime_config(
        resolved.for_crawl_runtime(runtime_overrides=overrides),
        json_safe=False,
    )
    runtime.update(normalize_runtime_config(overrides, json_safe=False))

    env = os.environ.copy()
    config_input_names = _archivebox_config_input_names()
    for key in config_input_names:
        env.pop(key, None)
    env.pop("PLUGINS", None)
    env["PATH"] = os.environ.get("PATH", "")
    env["DATA_DIR"] = str(CONSTANTS.DATA_DIR)
    env["LIBRARY_VERSION"] = VERSION
    env.setdefault("MACHINE_ID", os.environ.get("MACHINE_ID", CONSTANTS.MACHINE_ID))

    canonical_config_keys = set(ArchiveBoxConfig.model_fields)
    for key, value in runtime.items():
        if key == "PATH" or value is None:
            continue
        if key in config_input_names and key not in canonical_config_keys:
            continue
        if isinstance(value, bool):
            env[key] = "true" if value else "false"
        elif isinstance(value, (dict, list)):
            import json

            env[key] = json.dumps(value)
        else:
            env[key] = str(value)

    node_modules_dir = runtime.get("NODE_MODULES_DIR")
    lib_dir = runtime.get("ABXPKG_LIB_DIR")
    if not node_modules_dir and lib_dir:
        node_modules_dir = Path(lib_dir) / "pnpm" / "packages" / "chrome" / "node_modules"
    if node_modules_dir:
        env["NODE_MODULES_DIR"] = str(node_modules_dir)
        env["NODE_MODULE_DIR"] = str(node_modules_dir)
        node_path = [part for part in str(runtime.get("NODE_PATH") or "").split(os.pathsep) if part]
        if str(node_modules_dir) not in node_path:
            node_path.append(str(node_modules_dir))
        env["NODE_PATH"] = os.pathsep.join(node_path)
    return env, resolved


def run_hook(
    script: Path,
    output_dir: Path,
    config: ConfigLookup | Mapping[str, Any] | None = None,
    timeout: int | None = None,
    parent: Process | None = None,
    **kwargs: Any,
) -> Process:
    """Compatibility adapter for finite direct calls; abx-dl owns execution."""
    from archivebox.machine.models import Process
    from archivebox.services.process_service import ProcessService as PersistedProcessService
    from archivebox.services.process_service import parse_event_datetime
    from abx_dl.orchestrator import create_bus

    if parent is not None:
        kwargs.setdefault("_parent_process_id", str(parent.id))
    config_scope = {key.removeprefix("config_"): kwargs.pop(key) for key in list(kwargs) if key.startswith("config_")}
    env, resolved = _hook_environment(config, **config_scope)
    hook = _catalog_hook(script)
    if timeout is None:
        timeout = get_plugin_special_config(hook.plugin_name, resolved)["timeout"]
    timeout = min(int(timeout or 300), int(CONSTANTS.MAX_HOOK_RUNTIME_SECONDS))

    bus = create_bus(name=f"ArchiveBoxHook_{hook.plugin_name}", total_timeout=float(timeout) + 30.0)
    PersistedProcessService(bus)

    async def execute_and_close():
        try:
            return await execute_hook(
                hook,
                output_dir=output_dir,
                env=env,
                arguments=kwargs,
                timeout=timeout,
                bus=bus,
                process_type=Process.TypeChoices.HOOK,
            )
        finally:
            await bus.wait_until_idle()
            await bus.destroy(clear=False)

    completed = async_to_sync(execute_and_close)()
    started_at = parse_event_datetime(completed.start_ts)
    process = Process.objects.filter(pid=completed.pid or None, started_at=started_at).order_by("-modified_at").first()
    if process is None:
        raise RuntimeError(f"Hook {hook.full_name} completed without an ArchiveBox Process projection")
    return process


def extract_records_from_process(process: Process) -> list[dict[str, Any]]:
    """Return hook JSONL records with generic catalog identity attached."""
    records = process.get_records()
    plugin_name = Path(process.pwd).name if process.pwd else "unknown"
    plugin_hook = next((str(arg) for arg in process.cmd if Path(str(arg)).name.startswith("on_")), "")
    hook_name = Path(plugin_hook).name if plugin_hook else "unknown"
    for record in records:
        record.setdefault("plugin", plugin_name)
        record.setdefault("hook_name", hook_name)
        record.setdefault("plugin_hook", plugin_hook)
    return records


def collect_urls_from_plugins(snapshot_dir: Path) -> list[dict[str, Any]]:
    """Read the durable urls.jsonl interface emitted by parser plugins."""
    urls: list[dict[str, Any]] = []
    if not snapshot_dir.exists():
        return urls

    from archivebox.machine.models import Process

    for subdir in snapshot_dir.iterdir():
        urls_file = subdir / "urls.jsonl"
        if not subdir.is_dir() or not urls_file.is_file():
            continue
        try:
            for entry in Process.parse_records_from_text(urls_file.read_text()):
                if not entry.get("url"):
                    continue
                entry["url"] = sanitize_extracted_url(fix_url_from_markdown(str(entry["url"]).strip()))
                if entry["url"]:
                    entry["plugin"] = subdir.name
                    urls.append(entry)
        except (OSError, UnicodeError):
            continue
    return urls
