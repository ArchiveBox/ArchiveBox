"""
Hook discovery and execution helpers for ArchiveBox plugins.

ArchiveBox no longer drives plugin execution itself during normal crawls.
`abx-dl` owns the live runtime and emits typed bus events; ArchiveBox mainly:

- discovers hook files for inspection / docs / legacy direct execution helpers
- executes individual hook scripts when explicitly requested
- parses hook stdout JSONL records into ArchiveBox models when needed

Hook-backed event families are discovered from filenames like:
    on_BinaryRequest__*
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
    on_{EventFamily}__{run_order}_{description}[.finite.bg|.daemon.bg].{ext}

API:
    discover_hooks(event)     -> List[Path]     Find hook scripts for a hook-backed event family
    run_hook(script, ...)     -> Process        Execute a hook script directly
    is_background_hook(name)  -> bool           Check if hook is background (.bg suffix)
"""

__package__ = "archivebox"

import os
import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, TypedDict

from abx_plugins import get_plugins_dir
from django.conf import settings
from django.utils.safestring import mark_safe
from archivebox.config.constants import CONSTANTS
from archivebox.misc.util import fix_url_from_markdown, sanitize_extracted_url

if TYPE_CHECKING:
    from archivebox.machine.models import Process


# Plugin directories
BUILTIN_PLUGINS_DIR = Path(get_plugins_dir()).resolve()
USER_PLUGINS_DIR = Path(
    os.environ.get("ARCHIVEBOX_USER_PLUGINS_DIR") or getattr(settings, "USER_PLUGINS_DIR", "") or str(CONSTANTS.USER_PLUGINS_DIR),
).expanduser()


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


def is_finite_background_hook(hook_name: str) -> bool:
    """Check if a background hook is finite-lived and should be awaited."""
    return ".finite.bg." in hook_name


def iter_plugin_dirs() -> list[Path]:
    """Iterate over all built-in and user plugin directories."""
    plugin_dirs: list[Path] = []

    for base_dir in (BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR):
        if not base_dir.exists():
            continue

        for plugin_dir in base_dir.iterdir():
            if plugin_dir.is_dir() and not plugin_dir.name.startswith("_"):
                plugin_dirs.append(plugin_dir)

    return plugin_dirs


def normalize_hook_event_name(event_name: str) -> str | None:
    """
    Normalize a hook event family or event class name to its on_* prefix.

    Examples:
        BinaryRequestEvent -> BinaryRequest
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


class HookResult(TypedDict, total=False):
    """Raw result from run_hook()."""

    returncode: int
    stdout: str
    stderr: str
    output_json: dict[str, Any] | None
    output_files: list[dict[str, Any]]
    duration_ms: int
    hook: str
    plugin: str  # Plugin name (directory name, e.g., 'wget', 'screenshot')
    hook_name: str  # Full hook filename (e.g., 'on_Snapshot__50_wget.py')
    # New fields for JSONL parsing
    records: list[dict[str, Any]]  # Parsed JSONL records with 'type' field


def discover_hooks(
    event_name: str,
    filter_disabled: bool = True,
    config: dict[str, Any] | None = None,
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
            Examples: 'BinaryRequestEvent', 'Snapshot'.
            Event names are normalized by stripping a trailing `Event`.
            If no matching `on_{EventFamily}__*` scripts exist, returns [].
        filter_disabled: If True, skip hooks from disabled plugins (default: True)
        config: Optional config dict from get_config() (merges file, env, machine, crawl, snapshot)
                If None, will call get_config() with global scope

    Returns:
        Sorted list of hook script paths from enabled plugins only.

    Examples:
        # With proper config context (recommended):
        from archivebox.config.configset import get_config
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

    # Binary provider hooks are not end-user extractors. They
    # self-filter via `binproviders`, so applying the PLUGINS whitelist here
    # can hide the very installer needed by a selected plugin (e.g.
    # `--plugins=singlefile` still needs the `npm` BinaryRequest hook).
    if filter_disabled and hook_event_name != "BinaryRequest":
        # Get merged config if not provided (lazy import to avoid circular dependency)
        if config is None:
            from archivebox.config.configset import get_config

            config = get_config()

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

            # Check if plugin is enabled
            plugin_config = get_plugin_special_config(plugin_name, config)
            if plugin_config["enabled"]:
                enabled_hooks.append(hook)

        hooks = enabled_hooks

    # Sort by filename (not full path) to ensure numeric prefix ordering works
    # e.g., on_Snapshot__10_title.py sorts before on_Snapshot__26_readability.py
    return sorted(set(hooks), key=lambda p: p.name)


def run_hook(
    script: Path,
    output_dir: Path,
    config: dict[str, Any],
    timeout: int | None = None,
    parent: Optional["Process"] = None,
    **kwargs: Any,
) -> "Process":
    """
    Execute a hook script with the given arguments using Process model.

    This is the low-level hook executor that creates a Process record and
    uses Process.launch() for subprocess management.

    Config is passed to hooks via environment variables. Caller MUST use
    get_config() to merge all sources (file, env, machine, crawl, snapshot).

    Args:
        script: Path to the hook script (.sh, .py, or .js)
        output_dir: Working directory for the script (where output files go)
        config: Merged config dict from get_config(crawl=..., snapshot=...) - REQUIRED
        timeout: Maximum execution time in seconds
                 If None, auto-detects from PLUGINNAME_TIMEOUT config (fallback to TIMEOUT, default 300)
        parent: Optional parent Process (for tracking worker->hook hierarchy)
        **kwargs: Arguments passed to the script as --key=value

    Returns:
        Process model instance (use process.exit_code, process.stdout, process.get_records())

    Example:
        from archivebox.config.configset import get_config
        config = get_config(crawl=my_crawl, snapshot=my_snapshot)
        process = run_hook(hook_path, output_dir, config=config, url=url, snapshot_id=id)
        if process.status == 'exited':
            records = process.get_records()  # Get parsed JSONL output
    """
    from archivebox.machine.models import Process, Machine, NetworkInterface
    from archivebox.config.constants import CONSTANTS
    import sys

    # Auto-detect timeout from plugin config if not explicitly provided
    if timeout is None:
        plugin_name = script.parent.name
        plugin_config = get_plugin_special_config(plugin_name, config)
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

    if not script.exists():
        # Create a failed Process record for hooks that don't exist
        process = Process.objects.create(
            machine=machine,
            iface=iface,
            parent=parent,
            process_type=Process.TypeChoices.HOOK,
            pwd=str(output_dir),
            cmd=["echo", f"Hook script not found: {script}"],
            timeout=timeout,
            status=Process.StatusChoices.EXITED,
            exit_code=1,
            stderr=f"Hook script not found: {script}",
        )
        return process

    # Determine the interpreter based on file extension
    ext = script.suffix.lower()
    if ext == ".sh":
        cmd = ["bash", str(script)]
    elif ext == ".py":
        cmd = [sys.executable, str(script)]
    elif ext == ".js":
        cmd = ["node", str(script)]
    else:
        # Try to execute directly (assumes shebang)
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
    env["DATA_DIR"] = str(getattr(settings, "DATA_DIR", Path.cwd()))
    env["ARCHIVE_DIR"] = str(getattr(settings, "ARCHIVE_DIR", Path.cwd() / "archive"))
    env["ABX_RUNTIME"] = "archivebox"
    env.setdefault("MACHINE_ID", getattr(settings, "MACHINE_ID", "") or os.environ.get("MACHINE_ID", ""))

    resolved_output_dir = output_dir.resolve()
    output_parts = set(resolved_output_dir.parts)
    if "snapshots" in output_parts:
        env["SNAP_DIR"] = str(resolved_output_dir.parent)
    if "crawls" in output_parts:
        env["CRAWL_DIR"] = str(resolved_output_dir.parent)

    crawl_id = kwargs.get("_crawl_id") or kwargs.get("crawl_id")
    if crawl_id:
        try:
            from archivebox.crawls.models import Crawl

            crawl = Crawl.objects.filter(id=crawl_id).first()
            if crawl:
                env["CRAWL_DIR"] = str(crawl.output_dir)
        except Exception:
            pass

    # Get LIB_DIR and LIB_BIN_DIR from config
    lib_dir = config.get("LIB_DIR", getattr(settings, "LIB_DIR", None))
    lib_bin_dir = config.get("LIB_BIN_DIR", getattr(settings, "LIB_BIN_DIR", None))
    if lib_dir:
        env["LIB_DIR"] = str(lib_dir)
    if not lib_bin_dir and lib_dir:
        # Derive LIB_BIN_DIR from LIB_DIR if not set
        lib_bin_dir = Path(lib_dir) / "bin"

    # Set NODE_PATH for Node.js module resolution.
    # Priority: config dict > derive from LIB_DIR
    node_path = config.get("NODE_PATH")
    if not node_path and lib_dir:
        # Derive from LIB_DIR/npm/node_modules (create if needed)
        node_modules_dir = Path(lib_dir) / "npm" / "node_modules"
        node_modules_dir.mkdir(parents=True, exist_ok=True)
        node_path = str(node_modules_dir)
    if node_path:
        env["NODE_PATH"] = node_path
        env["NODE_MODULES_DIR"] = node_path  # For backwards compatibility

    # Export all config values to environment (already merged by get_config())
    # Skip keys we've already handled specially above (PATH, LIB_DIR, LIB_BIN_DIR, NODE_PATH, etc.)
    SKIP_KEYS = {
        "PATH",
        "LIB_DIR",
        "LIB_BIN_DIR",
        "NODE_PATH",
        "NODE_MODULES_DIR",
        "DATA_DIR",
        "ARCHIVE_DIR",
        "MACHINE_ID",
        "SNAP_DIR",
        "CRAWL_DIR",
    }
    for key, value in config.items():
        if key in SKIP_KEYS:
            continue  # Already handled specially above, don't overwrite
        if value is None:
            continue
        elif isinstance(value, bool):
            env[key] = "true" if value else "false"
        elif isinstance(value, (list, dict)):
            env[key] = json.dumps(value)
        else:
            env[key] = str(value)

    # Build PATH with proper precedence:
    # 1. path-like *_BINARY parents (explicit binary overrides / cached abspaths)
    # 2. LIB_BIN_DIR (local symlinked binaries)
    # 3. existing PATH
    runtime_bin_dirs: list[str] = []
    if lib_bin_dir:
        lib_bin_dir = str(lib_bin_dir)
        env["LIB_BIN_DIR"] = lib_bin_dir
    for key, raw_value in env.items():
        if not key.endswith("_BINARY"):
            continue
        value = str(raw_value or "").strip()
        if not value:
            continue
        path_value = Path(value).expanduser()
        if not (path_value.is_absolute() or "/" in value or "\\" in value):
            continue
        binary_dir = str(path_value.resolve(strict=False).parent)
        if binary_dir and binary_dir not in runtime_bin_dirs:
            runtime_bin_dirs.append(binary_dir)
    if lib_bin_dir and lib_bin_dir not in runtime_bin_dirs:
        runtime_bin_dirs.append(lib_bin_dir)
    uv_value = str(env.get("UV") or "").strip()
    if uv_value:
        uv_bin_dir = str(Path(uv_value).expanduser().resolve(strict=False).parent)
        if uv_bin_dir and uv_bin_dir not in runtime_bin_dirs:
            runtime_bin_dirs.append(uv_bin_dir)

    current_path = env.get("PATH", "")
    path_parts = [part for part in current_path.split(os.pathsep) if part]
    for extra_dir in reversed(runtime_bin_dirs):
        if extra_dir not in path_parts:
            path_parts.insert(0, extra_dir)
    env["PATH"] = os.pathsep.join(path_parts)

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    # Detect if this is a background hook (long-running daemon)
    # Background hooks use the .daemon.bg. or .finite.bg. filename convention.
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

    # Extract plugin metadata from process.pwd and process.cmd
    plugin_name = Path(process.pwd).name if process.pwd else "unknown"
    hook_name = Path(process.cmd[1]).name if len(process.cmd) > 1 else "unknown"
    plugin_hook = process.cmd[1] if len(process.cmd) > 1 else ""

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


@lru_cache(maxsize=1)
def get_plugins() -> list[str]:
    """
    Get list of available plugins by discovering plugin directories.

    Returns plugin directory names for any plugin that exposes hooks, config.json,
    or a standardized templates/icon.html asset. This includes non-extractor
    plugins such as binary providers and shared base plugins.
    """
    plugins = []

    for plugin_dir in iter_plugin_dirs():
        has_hooks = any(plugin_dir.glob("on_*__*.*"))
        has_config = (plugin_dir / "config.json").exists()
        has_icon = (plugin_dir / "templates" / "icon.html").exists()
        if has_hooks or has_config or has_icon:
            plugins.append(plugin_dir.name)

    return sorted(set(plugins))


def get_plugin_name(plugin: str) -> str:
    """
    Get the base plugin name without numeric prefix.

    Examples:
        '10_title' -> 'title'
        '26_readability' -> 'readability'
        '50_parse_html_urls' -> 'parse_html_urls'
    """
    # Split on first underscore after any leading digits
    parts = plugin.split("_", 1)
    if len(parts) == 2 and parts[0].isdigit():
        return parts[1]
    return plugin


def get_enabled_plugins(config: dict[str, Any] | None = None) -> list[str]:
    """
    Get the list of enabled plugins based on config and available hooks.

    Filters plugins by USE_/SAVE_ flags. Only returns plugins that are enabled.

    Args:
        config: Merged config dict from get_config() - if None, uses global config

    Returns:
        Plugin names sorted alphabetically (numeric prefix controls order).

    Example:
        from archivebox.config.configset import get_config
        config = get_config(crawl=my_crawl, snapshot=my_snapshot)
        enabled = get_enabled_plugins(config)  # ['wget', 'media', 'chrome', ...]
    """
    # Get merged config if not provided
    if config is None:
        from archivebox.config.configset import get_config

        config = get_config()

    def normalize_enabled_plugins(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    return [str(plugin).strip() for plugin in parsed if str(plugin).strip()]
            return [plugin.strip() for plugin in raw.split(",") if plugin.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(plugin).strip() for plugin in value if str(plugin).strip()]
        return [str(value).strip()] if str(value).strip() else []

    # Support explicit ENABLED_PLUGINS override (legacy)
    if "ENABLED_PLUGINS" in config:
        return normalize_enabled_plugins(config["ENABLED_PLUGINS"])
    if "ENABLED_EXTRACTORS" in config:
        return normalize_enabled_plugins(config["ENABLED_EXTRACTORS"])

    # Filter all plugins by enabled status
    all_plugins = get_plugins()
    enabled = []

    for plugin in all_plugins:
        plugin_config = get_plugin_special_config(plugin, config)
        if plugin_config["enabled"]:
            enabled.append(plugin)

    return enabled


def discover_plugins_that_provide_interface(
    module_name: str,
    required_attrs: list[str],
    plugin_prefix: str | None = None,
) -> dict[str, Any]:
    """
    Discover plugins that provide a specific Python module with required interface.

    This enables dynamic plugin discovery for features like search backends,
    storage backends, etc. without hardcoding imports.

    Args:
        module_name: Name of the module to look for (e.g., 'search')
        required_attrs: List of attributes the module must have (e.g., ['search', 'flush'])
        plugin_prefix: Optional prefix to filter plugins (e.g., 'search_backend_')

    Returns:
        Dict mapping backend names to imported modules.
        Backend name is derived from plugin directory name minus the prefix.
        e.g., search_backend_sqlite -> 'sqlite'

    Example:
        backends = discover_plugins_that_provide_interface(
            module_name='search',
            required_attrs=['search', 'flush'],
            plugin_prefix='search_backend_',
        )
        # Returns: {'sqlite': <module>, 'sonic': <module>, 'ripgrep': <module>}
    """
    import importlib.util

    backends = {}

    for base_dir in (BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR):
        if not base_dir.exists():
            continue

        for plugin_dir in base_dir.iterdir():
            if not plugin_dir.is_dir():
                continue

            plugin_name = plugin_dir.name

            # Filter by prefix if specified
            if plugin_prefix and not plugin_name.startswith(plugin_prefix):
                continue

            # Look for the module file
            module_path = plugin_dir / f"{module_name}.py"
            if not module_path.exists():
                continue

            try:
                # Import the module dynamically
                spec = importlib.util.spec_from_file_location(
                    f"archivebox.dynamic_plugins.{plugin_name}.{module_name}",
                    module_path,
                )
                if spec is None or spec.loader is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Check for required attributes
                if not all(hasattr(module, attr) for attr in required_attrs):
                    continue

                # Derive backend name from plugin directory name
                if plugin_prefix:
                    backend_name = plugin_name[len(plugin_prefix) :]
                else:
                    backend_name = plugin_name

                backends[backend_name] = module

            except Exception:
                # Skip plugins that fail to import
                continue

    return backends


def get_search_backends() -> dict[str, Any]:
    """
    Discover all available search backend plugins.

    Search backends must provide a search.py module with:
        - search(query: str) -> List[str]  (returns snapshot IDs)
        - flush(snapshot_ids: Iterable[str]) -> None

    Returns:
        Dict mapping backend names to their modules.
        e.g., {'sqlite': <module>, 'sonic': <module>, 'ripgrep': <module>}
    """
    return discover_plugins_that_provide_interface(
        module_name="search",
        required_attrs=["search", "flush"],
        plugin_prefix="search_backend_",
    )


def discover_plugin_configs() -> dict[str, dict[str, Any]]:
    """
    Discover all plugin config.json schemas.

    Each plugin can define a config.json file with JSONSchema defining
    its configuration options. This function discovers and loads all such schemas.

    The config.json files use JSONSchema draft-07 with custom extensions:
        - x-fallback: Global config key to use as fallback
        - x-aliases: List of old/alternative config key names

    Returns:
        Dict mapping plugin names to their parsed JSONSchema configs.
        e.g., {'wget': {...schema...}, 'chrome': {...schema...}}

    Example config.json:
        {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "SAVE_WGET": {"type": "boolean", "default": true},
                "WGET_TIMEOUT": {"type": "integer", "default": 60, "x-fallback": "TIMEOUT"}
            }
        }
    """
    configs = {}

    for plugin_dir in iter_plugin_dirs():
        config_path = plugin_dir / "config.json"
        if not config_path.exists():
            continue

        try:
            with open(config_path) as f:
                schema = json.load(f)

            # Basic validation: must be an object with properties
            if not isinstance(schema, dict):
                continue
            if schema.get("type") != "object":
                continue
            if "properties" not in schema:
                continue

            configs[plugin_dir.name] = schema

        except (json.JSONDecodeError, OSError) as e:
            # Log warning but continue - malformed config shouldn't break discovery
            import sys

            print(f"Warning: Failed to load config.json from {plugin_dir.name}: {e}", file=sys.stderr)
            continue

    return configs


def get_config_defaults_from_plugins() -> dict[str, Any]:
    """
    Get default values for all plugin config options.

    Returns:
        Dict mapping config keys to their default values.
        e.g., {'SAVE_WGET': True, 'WGET_TIMEOUT': 60, ...}
    """
    plugin_configs = discover_plugin_configs()
    defaults = {}

    for plugin_name, schema in plugin_configs.items():
        properties = schema.get("properties", {})
        for key, prop_schema in properties.items():
            if "default" in prop_schema:
                defaults[key] = prop_schema["default"]

    return defaults


def get_plugin_special_config(plugin_name: str, config: dict[str, Any], _visited: set[str] | None = None) -> dict[str, Any]:
    """
    Extract special config keys for a plugin following naming conventions.

    ArchiveBox recognizes 3 special config key patterns per plugin:
        - {PLUGIN}_ENABLED: Enable/disable toggle (default True)
        - {PLUGIN}_TIMEOUT: Plugin-specific timeout (fallback to TIMEOUT, default 300)
        - {PLUGIN}_BINARY: Primary binary path (default to plugin_name)

    These allow ArchiveBox to:
        - Skip disabled plugins (optimization)
        - Enforce plugin-specific timeouts automatically
        - Discover plugin binaries for validation

    Args:
        plugin_name: Plugin name (e.g., 'wget', 'media', 'chrome')
        config: Merged config dict from get_config() (properly merges file, env, machine, crawl, snapshot)

    Returns:
        Dict with standardized keys:
            {
                'enabled': True,         # bool
                'timeout': 60,           # int, seconds
                'binary': 'wget',        # str, path or name
            }

    Examples:
        >>> from archivebox.config.configset import get_config
        >>> config = get_config(crawl=my_crawl, snapshot=my_snapshot)
        >>> get_plugin_special_config('wget', config)
        {'enabled': True, 'timeout': 120, 'binary': '/usr/bin/wget'}
    """
    plugin_upper = plugin_name.upper()

    # 1. Enabled: Check PLUGINS whitelist first, then PLUGINNAME_ENABLED (default True)
    # Old names (USE_*, SAVE_*) are aliased in config.json via x-aliases

    # Check if PLUGINS whitelist is specified (e.g., --plugins=wget,favicon)
    plugins_whitelist = config.get("PLUGINS", "")
    if plugins_whitelist:
        # PLUGINS whitelist is specified - include transitive required_plugins from
        # config.json so selecting a plugin also enables its declared plugin-level
        # dependencies (e.g. singlefile -> chrome).
        plugin_configs = discover_plugin_configs()
        plugin_names = {p.strip().lower() for p in plugins_whitelist.split(",") if p.strip()}
        pending = list(plugin_names)

        while pending:
            current = pending.pop()
            schema = plugin_configs.get(current, {})
            required_plugins = schema.get("required_plugins", [])
            if not isinstance(required_plugins, list):
                continue

            for required_plugin in required_plugins:
                required_plugin_name = str(required_plugin).strip().lower()
                if not required_plugin_name or required_plugin_name in plugin_names:
                    continue
                plugin_names.add(required_plugin_name)
                pending.append(required_plugin_name)

        if plugin_name.lower() not in plugin_names:
            # Plugin not in whitelist - explicitly disabled
            enabled = False
        else:
            # Plugin is in whitelist - check if explicitly disabled by PLUGINNAME_ENABLED
            enabled_key = f"{plugin_upper}_ENABLED"
            enabled = config.get(enabled_key)
            if enabled is None:
                enabled = True  # Default to enabled if in whitelist
            elif isinstance(enabled, str):
                enabled = enabled.lower() not in ("false", "0", "no", "")
    else:
        # No PLUGINS whitelist - use PLUGINNAME_ENABLED (default True)
        enabled_key = f"{plugin_upper}_ENABLED"
        enabled = config.get(enabled_key)
        if enabled is None:
            enabled = True
        elif isinstance(enabled, str):
            # Handle string values from config file ("true"/"false")
            enabled = enabled.lower() not in ("false", "0", "no", "")

    plugin_configs = discover_plugin_configs()
    plugin_name_lower = plugin_name.lower()

    if enabled:
        visited = _visited or set()
        if plugin_name_lower not in visited:
            next_visited = visited | {plugin_name_lower}
            schema = plugin_configs.get(plugin_name_lower, {})
            required_plugins = schema.get("required_plugins", [])
            if isinstance(required_plugins, list):
                for required_plugin in required_plugins:
                    required_plugin_name = str(required_plugin).strip()
                    if not required_plugin_name:
                        continue
                    required_config = get_plugin_special_config(required_plugin_name, config, _visited=next_visited)
                    if not required_config["enabled"]:
                        enabled = False
                        break

    # 2. Timeout: PLUGINNAME_TIMEOUT (fallback to TIMEOUT, default 300)
    timeout_key = f"{plugin_upper}_TIMEOUT"
    timeout = config.get(timeout_key) or config.get("TIMEOUT", 300)

    # 3. Binary: PLUGINNAME_BINARY (default to plugin_name)
    binary_key = f"{plugin_upper}_BINARY"
    binary = config.get(binary_key, plugin_name)

    return {
        "enabled": bool(enabled),
        "timeout": int(timeout),
        "binary": str(binary),
    }


# =============================================================================
# Plugin Template Discovery
# =============================================================================
#
# Plugins can provide custom templates for rendering their output in the UI.
# Templates are discovered by filename convention inside each plugin's templates/ dir:
#
#     abx_plugins/plugins/<plugin_name>/
#         templates/
#             icon.html          # Icon for admin table view (small inline HTML)
#             card.html          # Preview card for snapshot header
#             full.html          # Fullscreen view template
#
# Template context variables available:
#     {{ result }}         - ArchiveResult object
#     {{ snapshot }}       - Parent Snapshot object
#     {{ output_path }}    - Path to output file/dir relative to snapshot dir
#     {{ plugin }}         - Plugin name (e.g., 'screenshot', 'singlefile')
#

# Default templates used when plugin doesn't provide one
DEFAULT_TEMPLATES = {
    "icon": """
        <span title="{{ plugin }}" style="display:inline-flex; width:20px; height:20px; align-items:center; justify-content:center;">
            {{ icon }}
        </span>
    """,
    "card": """
        <iframe src="{{ output_path }}"
                class="card-img-top"
                style="width: 100%; height: 100%; border: none;"
                sandbox="allow-same-origin allow-scripts allow-forms"
                loading="lazy">
        </iframe>
    """,
    "full": """
        <iframe src="{{ output_path }}"
                class="full-page-iframe"
                style="width: 100%; height: 100vh; border: none;"
                sandbox="allow-same-origin allow-scripts allow-forms">
        </iframe>
    """,
}


def get_plugin_template(plugin: str, template_name: str, fallback: bool = True) -> str | None:
    """
    Get a plugin template by plugin name and template type.

    Args:
        plugin: Plugin name (e.g., 'screenshot', '15_singlefile')
        template_name: One of 'icon', 'card', 'full'
        fallback: If True, return default template if plugin template not found

    Returns:
        Template content as string, or None if not found and fallback=False.
    """
    base_name = get_plugin_name(plugin)
    if base_name in ("yt-dlp", "youtube-dl"):
        base_name = "ytdlp"

    for plugin_dir in iter_plugin_dirs():
        # Match by directory name (exact or partial)
        if plugin_dir.name == base_name or plugin_dir.name.endswith(f"_{base_name}"):
            template_path = plugin_dir / "templates" / f"{template_name}.html"
            if template_path.exists():
                return template_path.read_text()

    # Fall back to default template if requested
    if fallback:
        return DEFAULT_TEMPLATES.get(template_name, "")

    return None


@lru_cache(maxsize=None)
def get_plugin_icon(plugin: str) -> str:
    """
    Get the icon for a plugin from its icon.html template.

    Args:
        plugin: Plugin name (e.g., 'screenshot', '15_singlefile')

    Returns:
        Icon HTML/emoji string.
    """
    # Try plugin-provided icon template
    icon_template = get_plugin_template(plugin, "icon", fallback=False)
    if icon_template:
        return mark_safe(icon_template.strip())

    # Fall back to generic folder icon
    return mark_safe("📁")


# =============================================================================
# Hook Result Processing Helpers
# =============================================================================


def process_hook_records(records: list[dict[str, Any]], overrides: dict[str, Any] | None = None) -> dict[str, int]:
    """
    Process JSONL records emitted by hook stdout.

    This handles hook-emitted record types such as Snapshot, Tag, BinaryRequest,
    and Binary. It does not process internal bus lifecycle events, since those
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

            elif record_type in {"BinaryRequest", "Binary"}:
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
