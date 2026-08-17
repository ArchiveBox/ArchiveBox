"""
Hook discovery and execution helpers for ArchiveBox plugins.

ArchiveBox no longer drives plugin execution itself during normal crawls.
`abx-dl` owns the live runtime and emits typed bus events; ArchiveBox mainly:

- discovers hook files for inspection / docs / legacy direct execution helpers
- executes individual hook scripts when explicitly requested
- parses hook stdout JSONL records into ArchiveBox models when needed

Hook-backed event families are discovered from filenames like:
    on_CrawlSetup__*
    on_Snapshot__*

Internal bus event names are normalized to the corresponding
`on_{EventFamily}__*` prefix by a simple string transform. If no scripts exist
for that prefix, discovery returns `[]`.

Directory structure:
    abx_plugins/plugins/<plugin_name>/on_<Event>__<hook_name>.<ext>     (built-in package)
    data/custom_plugins/<plugin_name>/on_<Event>__<hook_name>.<ext>     (user)

Hook contract:
    Input:  --url=<url> (and other --key=value args)
    Output: JSONL records to stdout, files to $PWD
    Exit:   0 = success, non-zero = failure

Execution order:
    - Hooks are named with two-digit prefixes (00-99) and sorted lexicographically by filename
    - Foreground hooks run sequentially in that order
    - Background hooks (.bg suffix) run concurrently and do not block foreground progress
    - After all foreground hooks complete, background hooks receive SIGTERM and must finalize

Hook naming convention:
    on_{EventFamily}__{run_order}_{description}[.bg].{ext}

API:
    discover_hooks(event)     -> List[Path]     Find hook scripts for a hook-backed event family
    run_hook(script, ...)     -> Process        Execute a hook script directly
    is_background_hook(name)  -> bool           Check if hook is background (.bg suffix)
"""

__package__ = "archivebox.plugins"

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Protocol, TypeGuard, runtime_checkable

from archivebox.config.constants import CONSTANTS
from archivebox.config.version import VERSION
from archivebox.misc.util import fix_url_from_markdown, sanitize_extracted_url
from archivebox.plugins.discovery import (
    BUILTIN_PLUGINS_DIR,
    USER_PLUGINS_DIR,
    ConfigLookup,
    get_enabled_plugins,
    get_plugin_special_config,
)

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


# =============================================================================
# Hook Step Extraction
# =============================================================================


def is_background_hook(hook_name: str) -> bool:
    """
    Check if a hook is a background hook (doesn't block foreground progression).

    Background hooks have '.bg.' in their filename before the extension.

    Args:
        hook_name: Hook filename (e.g., 'on_Snapshot__10_chrome_tab.daemon.bg.js')

    Returns:
        True if background hook, False if foreground.

    Examples:
        is_background_hook('on_Snapshot__10_chrome_tab.daemon.bg.js') -> True
        is_background_hook('on_Snapshot__50_wget.py') -> False
        is_background_hook('on_Snapshot__63_media.finite.bg.py') -> True
    """
    return ".bg." in hook_name or "__background" in hook_name


def normalize_hook_event_name(event_name: str) -> str | None:
    """
    Normalize a hook event family or event class name to its on_* prefix.

    Examples:
        CrawlSetupEvent -> CrawlSetup
        SnapshotEvent -> Snapshot
        BinaryEvent -> Binary
        CrawlCleanupEvent -> CrawlCleanup
    """
    normalized = str(event_name or "").strip()
    if not normalized:
        return None

    if normalized.endswith("Event"):
        return normalized[:-5] or None
    return normalized


def _model_output_dir_from_child_path(path: Path, marker: str) -> Path | None:
    """
    Infer the model output dir from a model dir or one of its plugin subdirs.

    Current ArchiveBox snapshot/crawl dirs are:
        .../{snapshots,crawls}/YYYYMMDD/domain/uuid[/plugin]
    """
    parts = path.resolve().parts
    try:
        marker_index = parts.index(marker)
    except ValueError:
        return None

    model_end_index = marker_index + 4
    if len(parts) < model_end_index:
        return None
    return Path(*parts[:model_end_index])


def discover_hooks(
    event_name: str,
    filter_disabled: bool = True,
    config: ConfigLookup | None = None,
    **config_kwargs: Any,
) -> list[Path]:
    """
    Find all hook scripts for an event family.

    Searches both built-in and user plugin directories.
    Filters out hooks from disabled plugins by default (respects USE_/SAVE_ flags).
    Returns scripts sorted alphabetically by filename for deterministic execution order.

    Hook naming convention uses numeric prefixes to control order:
        on_Snapshot__10_title.py        # runs first
        on_Snapshot__15_singlefile.py   # runs second
        on_Snapshot__26_readability.py  # runs later (depends on singlefile)

    Args:
        event_name: Hook event family or event class name.
            Examples: 'CrawlSetupEvent', 'Snapshot'.
            Event names are normalized by stripping a trailing `Event`.
            If no matching `on_{EventFamily}__*` scripts exist, returns [].
        filter_disabled: If True, skip hooks from disabled plugins (default: True)
        config: Optional pre-merged config dict from get_config().
        **config_kwargs: Scope/override args forwarded to get_config() when config is not supplied.

    Returns:
        Sorted list of hook script paths from enabled plugins only.

    Examples:
        # With proper config context (recommended):
        from archivebox.config.common import get_config
        config = get_config(crawl=my_crawl, snapshot=my_snapshot)
        discover_hooks('Snapshot', config=config)
        # Returns: [Path('.../on_Snapshot__10_title.py'), ...] (wget excluded if SAVE_WGET=False)

        # Without config (uses global defaults):
        discover_hooks('Snapshot')
        # Returns: [Path('.../on_Snapshot__10_title.py'), ...]

        # Show all plugins regardless of enabled status:
        discover_hooks('Snapshot', filter_disabled=False)
        # Returns: [Path('.../on_Snapshot__10_title.py'), ..., Path('.../on_Snapshot__50_wget.py')]
    """
    hook_event_name = normalize_hook_event_name(event_name)
    if not hook_event_name:
        return []
    if hook_event_name == "BinaryRequest":
        return []

    hooks = []

    for base_dir in (BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR):
        if not base_dir.exists():
            continue

        # Search for hook scripts in all subdirectories
        for ext in ("sh", "py", "js"):
            pattern = f"*/on_{hook_event_name}__*.{ext}"
            hooks.extend(base_dir.glob(pattern))

            # Also check for hooks directly in the plugins directory
            pattern_direct = f"on_{hook_event_name}__*.{ext}"
            hooks.extend(base_dir.glob(pattern_direct))

    if filter_disabled:
        # Get merged config if not provided (lazy import to avoid circular dependency)
        if config is None:
            from archivebox.config.common import get_config

            config = get_config(**config_kwargs)

        enabled_plugins = set(get_enabled_plugins(config=config))
        enabled_hooks = []

        for hook in hooks:
            # Get plugin name from parent directory
            # e.g., abx_plugins/plugins/wget/on_Snapshot__50_wget.py -> 'wget'
            plugin_name = hook.parent.name

            # Check if this is a plugin directory (not the root plugins dir)
            if hook.parent.resolve() in (BUILTIN_PLUGINS_DIR.resolve(), USER_PLUGINS_DIR.resolve()):
                # Hook is in root plugins directory, not a plugin subdir
                # Include it by default (no filtering for non-plugin hooks)
                enabled_hooks.append(hook)
                continue

            if plugin_name in enabled_plugins:
                enabled_hooks.append(hook)

        hooks = enabled_hooks

    # Sort by filename (not full path) to ensure numeric prefix ordering works
    # e.g., on_Snapshot__10_title.py sorts before on_Snapshot__26_readability.py
    return sorted(set(hooks), key=lambda p: p.name)


def run_hook(
    script: Path,
    output_dir: Path,
    config: ConfigLookup | Mapping[str, Any] | None = None,
    timeout: int | None = None,
    parent: Optional["Process"] = None,
    **kwargs: Any,
) -> "Process":
    """
    Execute a hook script with the given arguments using Process model.

    This is the low-level hook executor that creates a Process record and
    uses Process.launch() for subprocess management.

    Config is passed to hooks via environment variables. Crawl/snapshot callers
    should pass the runtime config produced by for_crawl_runtime().

    Args:
        script: Path to the hook script (.sh, .py, or .js)
        output_dir: Working directory for the script (where output files go)
        config: Optional runtime config dict from for_crawl_runtime().
                If omitted, pass scope/override args using kwargs prefixed with config_.
        timeout: Maximum execution time in seconds
                 If None, auto-detects from PLUGINNAME_TIMEOUT config (fallback to TIMEOUT, default 300)
        parent: Optional parent Process (for tracking worker->hook hierarchy)
        **kwargs: Arguments passed to the script as --key=value

    Returns:
        Process model instance (use process.exit_code, process.stdout, process.get_records())

    Example:
        from archivebox.config.common import get_config
        config = get_config(crawl=my_crawl, snapshot=my_snapshot).for_crawl_runtime(crawl=my_crawl, snapshot=my_snapshot)
        process = run_hook(hook_path, output_dir, config=config, url=url, snapshot_id=id)
        if process.status == 'exited':
            records = process.get_records()  # Get parsed JSONL output
    """
    from archivebox.machine.models import Process, Machine, NetworkInterface
    from archivebox.config.common import (
        ArchiveBoxConfig,
        _archivebox_config_input_names,
        get_config,
        normalize_runtime_config,
        _plugin_enabled_config_keys,
    )

    config_scope = {key.removeprefix("config_"): kwargs.pop(key) for key in list(kwargs) if key.startswith("config_")}
    config_overrides = _config_to_overrides(config)
    explicit_override_keys = set(config_overrides)
    resolved_config = get_config(overrides=config_overrides, **config_scope)
    hook_config = normalize_runtime_config(
        resolved_config.for_crawl_runtime(runtime_overrides=config_overrides),
        json_safe=False,
    )
    hook_config.update(normalize_runtime_config(config_overrides, json_safe=False))
    plugin_enabled_keys = set(_plugin_enabled_config_keys().values())
    if plugin_enabled_keys.intersection(hook_config):
        for enabled_key in plugin_enabled_keys:
            hook_config.setdefault(enabled_key, False)

    # Auto-detect timeout from plugin config if not explicitly provided
    if timeout is None:
        plugin_name = script.parent.name
        plugin_config = get_plugin_special_config(plugin_name, resolved_config)
        timeout = plugin_config["timeout"]
    if timeout:
        timeout = min(int(timeout), int(CONSTANTS.MAX_HOOK_RUNTIME_SECONDS))

    # Get current machine
    machine = Machine.current()
    iface = NetworkInterface.current(refresh=True)
    machine = iface.machine

    # Auto-detect parent process if not explicitly provided
    # This enables automatic hierarchy tracking: Worker -> Hook
    if parent is None:
        try:
            parent = Process.current()
        except Exception:
            # If Process.current() fails (e.g., not in a worker context), leave parent as None
            pass

    if not script.is_file():
        raise FileNotFoundError(f"Hook script not found: {script}")

    # Hooks are opaque executables. Their shipped abxpkg shebang owns runtime
    # and dependency resolution just as it does under abx-dl.
    cmd = [str(script)]

    # Build CLI arguments from kwargs
    for key, value in kwargs.items():
        # Skip keys that start with underscore (internal parameters)
        if key.startswith("_"):
            continue

        arg_key = f"--{key.replace('_', '-')}"
        if isinstance(value, bool):
            if value:
                cmd.append(arg_key)
        elif value is not None and value != "":
            # JSON-encode complex values, use str for simple ones
            # Skip empty strings to avoid --key= which breaks argument parsers
            if isinstance(value, (dict, list)):
                cmd.append(f"{arg_key}={json.dumps(value)}")
            else:
                # Ensure value is converted to string and strip whitespace
                str_value = str(value).strip()
                if str_value:  # Only add if non-empty after stripping
                    cmd.append(f"{arg_key}={str_value}")

    # Set up environment with base paths
    env = os.environ.copy()
    archivebox_config_input_names = _archivebox_config_input_names()
    for key in archivebox_config_input_names:
        env.pop(key, None)
    env.pop("PLUGINS", None)
    env["DATA_DIR"] = str(CONSTANTS.DATA_DIR)
    env["LIBRARY_VERSION"] = VERSION
    env.setdefault("MACHINE_ID", os.environ.get("MACHINE_ID", CONSTANTS.MACHINE_ID))
    snap_dir = hook_config.get("SNAP_DIR") or _model_output_dir_from_child_path(output_dir, CONSTANTS.SNAPSHOTS_DIR_NAME)
    crawl_dir = hook_config.get("CRAWL_DIR") or _model_output_dir_from_child_path(output_dir, CONSTANTS.CRAWLS_DIR_NAME)
    if snap_dir:
        env["SNAP_DIR"] = str(snap_dir)
    if crawl_dir:
        env["CRAWL_DIR"] = str(crawl_dir)

    # Export the runtime library root; abx-dl/abxpkg own executable lookup env.
    lib_dir = hook_config.get("ABXPKG_LIB_DIR")
    if lib_dir:
        env["ABXPKG_LIB_DIR"] = str(lib_dir)

    # Set Node.js module resolution paths.
    # NODE_PATH may be a path list, but NODE_MODULES_DIR is a single canonical directory.
    node_modules_dir = hook_config.get("NODE_MODULES_DIR")
    if lib_dir and "ABXPKG_LIB_DIR" in explicit_override_keys and "NODE_MODULES_DIR" not in explicit_override_keys:
        node_modules_dir = Path(lib_dir) / "pnpm" / "packages" / "chrome" / "node_modules"
    elif not node_modules_dir and lib_dir:
        node_modules_dir = Path(lib_dir) / "pnpm" / "packages" / "chrome" / "node_modules"

    node_path_parts = [part for part in str(hook_config.get("NODE_PATH") or "").split(os.pathsep) if part]
    if node_modules_dir:
        node_modules_dir = Path(node_modules_dir)
        node_modules_dir.mkdir(parents=True, exist_ok=True)
        node_modules_dir_str = str(node_modules_dir)
        env["NODE_MODULES_DIR"] = node_modules_dir_str
        env["NODE_MODULE_DIR"] = node_modules_dir_str
        if node_modules_dir_str not in node_path_parts:
            node_path_parts.append(node_modules_dir_str)
    if node_path_parts:
        env["NODE_PATH"] = os.pathsep.join(node_path_parts)

    # Export all config values to environment (already merged by get_config())
    # Skip keys we've already handled specially above (PATH, ABXPKG_LIB_DIR, NODE_PATH, etc.)
    SKIP_KEYS = {
        "PATH",
        "ABXPKG_LIB_DIR",
        "NODE_PATH",
        "NODE_MODULES_DIR",
        "NODE_MODULE_DIR",
        "DATA_DIR",
        "MACHINE_ID",
        "SNAP_DIR",
        "CRAWL_DIR",
    }
    canonical_config_keys = set(ArchiveBoxConfig.model_fields)
    for key, value in hook_config.items():
        if key in SKIP_KEYS:
            continue  # Already handled specially above, don't overwrite
        if key in archivebox_config_input_names and key not in canonical_config_keys:
            continue
        if value is None:
            continue
        elif isinstance(value, bool):
            env[key] = "true" if value else "false"
        elif isinstance(value, (list, dict)):
            env[key] = json.dumps(value)
        else:
            env[key] = str(value)

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    # Detect if this is a background hook.
    # Background hooks use the .bg. filename marker.
    # Old convention: __background in stem (for backwards compatibility)
    is_background = ".bg." in script.name or "__background" in script.stem

    try:
        # Create Process record
        process = Process.objects.create(
            machine=machine,
            iface=iface,
            parent=parent,
            process_type=Process.TypeChoices.HOOK,
            pwd=str(output_dir),
            cmd=cmd,
            timeout=timeout,
        )

        # Copy the env dict we already built (includes os.environ + all customizations)
        process.env = env.copy()
        process.hydrate_binary_from_context(plugin_name=script.parent.name, hook_path=str(script))

        # Save env before launching
        process.save()

        # Launch subprocess using Process.launch()
        process.launch(background=is_background)

        # Return Process object (caller can use process.exit_code, process.stdout, process.get_records())
        return process

    except Exception as e:
        # Create a failed Process record for exceptions
        process = Process.objects.create(
            machine=machine,
            iface=iface,
            process_type=Process.TypeChoices.HOOK,
            pwd=str(output_dir),
            cmd=cmd,
            timeout=timeout,
            status=Process.StatusChoices.EXITED,
            exit_code=1,
            stderr=f"Failed to run hook: {type(e).__name__}: {e}",
        )
        return process


def extract_records_from_process(process: "Process") -> list[dict[str, Any]]:
    """
    Extract JSONL records from a Process's stdout.

    Adds plugin metadata to each record.

    Args:
        process: Process model instance with stdout captured

    Returns:
        List of parsed JSONL records with plugin metadata
    """
    records = process.get_records()
    if not records:
        return []

    # Extract plugin metadata from process.pwd and the shipped hook path in cmd.
    # Python hooks execute directly through their shebang, while JS and shell
    # hooks have an interpreter in cmd[0].
    plugin_name = Path(process.pwd).name if process.pwd else "unknown"
    plugin_hook = next((str(arg) for arg in process.cmd if Path(str(arg)).name.startswith("on_")), "")
    hook_name = Path(plugin_hook).name if plugin_hook else "unknown"

    for record in records:
        # Add plugin metadata to record
        record.setdefault("plugin", plugin_name)
        record.setdefault("hook_name", hook_name)
        record.setdefault("plugin_hook", plugin_hook)

    return records


def collect_urls_from_plugins(snapshot_dir: Path) -> list[dict[str, Any]]:
    """
    Collect all urls.jsonl entries from parser plugin output subdirectories.

    Each parser plugin outputs urls.jsonl to its own subdir:
        snapshot_dir/parse_rss_urls/urls.jsonl
        snapshot_dir/parse_html_urls/urls.jsonl
        etc.

    This is not special handling - urls.jsonl is just a normal output file.
    This utility collects them all for the crawl system.
    """
    urls = []

    # Look in each immediate subdirectory for urls.jsonl
    if not snapshot_dir.exists():
        return urls

    for subdir in snapshot_dir.iterdir():
        if not subdir.is_dir():
            continue

        urls_file = subdir / "urls.jsonl"
        if not urls_file.exists():
            continue

        try:
            from archivebox.machine.models import Process

            text = urls_file.read_text()
            for entry in Process.parse_records_from_text(text):
                if entry.get("url"):
                    entry["url"] = sanitize_extracted_url(fix_url_from_markdown(str(entry["url"]).strip()))
                    if not entry["url"]:
                        continue
                    # Track which parser plugin found this URL
                    entry["plugin"] = subdir.name
                    urls.append(entry)
        except Exception:
            pass

    return urls


# =============================================================================
# Hook Result Processing Helpers
# =============================================================================


def process_hook_records(records: list[dict[str, Any]], overrides: dict[str, Any] | None = None) -> dict[str, int]:
    """
    Process JSONL records emitted by hook stdout.

    This handles hook-emitted record types such as Snapshot, Tag, and Binary.
    It does not process internal bus lifecycle events, since those
    are not emitted as JSONL records by hook subprocesses.

    Args:
        records: List of JSONL record dicts from result['records']
        overrides: Dict with 'snapshot', 'crawl', 'dependency', 'created_by_id', etc.

    Returns:
        Dict with counts by record type
    """
    stats = {}
    overrides = overrides or {}

    for record in records:
        record_type = record.get("type")
        if not record_type:
            continue

        # Skip ArchiveResult records (they update the calling ArchiveResult, not create new ones)
        if record_type == "ArchiveResult":
            continue

        try:
            # Dispatch to appropriate model's from_json() method
            if record_type == "Snapshot":
                from archivebox.core.models import Snapshot

                if record.get("url"):
                    record = {
                        **record,
                        "url": sanitize_extracted_url(fix_url_from_markdown(str(record["url"]).strip())),
                    }
                    if not record["url"]:
                        continue

                # Check if discovered snapshot exceeds crawl max_depth
                snapshot_depth = record.get("depth", 0)
                crawl = overrides.get("crawl")
                if crawl and snapshot_depth > crawl.max_depth:
                    # Skip - this URL was discovered but exceeds max crawl depth
                    continue

                obj = Snapshot.from_json(record.copy(), overrides)
                if obj:
                    stats["Snapshot"] = stats.get("Snapshot", 0) + 1

            elif record_type == "Tag":
                from archivebox.core.models import Tag

                obj = Tag.from_json(record.copy(), overrides)
                if obj:
                    stats["Tag"] = stats.get("Tag", 0) + 1

            elif record_type == "Binary":
                from archivebox.machine.models import Binary

                obj = Binary.from_json(record.copy(), overrides)
                if obj:
                    stats[record_type] = stats.get(record_type, 0) + 1

            else:
                import sys

                print(f"Warning: Unknown record type '{record_type}' from hook output", file=sys.stderr)

        except Exception as e:
            import sys

            print(f"Warning: Failed to create {record_type}: {e}", file=sys.stderr)
            continue

    return stats
