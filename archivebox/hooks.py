"""
Hook discovery and execution system for ArchiveBox plugins.

Hooks are standalone scripts that run as separate processes and communicate
with ArchiveBox via CLI arguments and stdout JSON output. This keeps the plugin
system simple and language-agnostic.

Directory structure:
    archivebox/plugins/<plugin_name>/on_<Event>__<hook_name>.<ext>  (built-in)
    data/plugins/<plugin_name>/on_<Event>__<hook_name>.<ext>        (user)

Hook contract:
    Input:  --url=<url> (and other --key=value args)
    Output: JSON to stdout, files to $PWD
    Exit:   0 = success, non-zero = failure

Execution order:
    - Hooks are numbered 00-99 with first digit determining step (0-9)
    - All hooks in a step can run in parallel
    - Steps execute sequentially (step 0 → step 1 → ... → step 9)
    - Background hooks (.bg suffix) don't block step advancement
    - Failed extractors don't block subsequent extractors

Hook Naming Convention:
    on_{ModelName}__{run_order}_{description}[.bg].{ext}

    Examples:
        on_Snapshot__00_setup.py         # Step 0, runs first
        on_Snapshot__20_chrome_tab.bg.js # Step 2, background (doesn't block)
        on_Snapshot__50_screenshot.js    # Step 5, foreground (blocks step)
        on_Snapshot__63_media.bg.py      # Step 6, background (long-running)

Dependency handling:
    Extractor plugins that depend on other plugins' output should check at runtime:

    ```python
    # Example: screenshot plugin depends on chrome plugin
    chrome_session_dir = Path(os.environ.get('SNAPSHOT_DIR', '.')) / 'chrome_session'
    if not (chrome_session_dir / 'session.json').exists():
        print('{"status": "skipped", "output": "chrome_session not available"}')
        sys.exit(1)  # Exit non-zero so it gets retried later
    ```

    On retry (Snapshot.retry_failed_archiveresults()):
    - Only FAILED/SKIPPED plugins reset to queued (SUCCEEDED stays)
    - Run in order again
    - If dependencies now succeed, dependents can run

API (all hook logic lives here):
    discover_hooks(event)     -> List[Path]     Find hook scripts
    run_hook(script, ...)     -> HookResult     Execute a hook script
    run_hooks(event, ...)     -> List[HookResult]  Run all hooks for an event
    extract_step(hook_name)   -> int            Get step number (0-9) from hook name
    is_background_hook(name)  -> bool           Check if hook is background (.bg suffix)
"""

__package__ = 'archivebox'

import os
import re
import json
import signal
import time
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, TypedDict

from django.conf import settings
from django.utils import timezone


# Plugin directories
BUILTIN_PLUGINS_DIR = Path(__file__).parent / 'plugins'
USER_PLUGINS_DIR = Path(getattr(settings, 'DATA_DIR', Path.cwd())) / 'plugins'


# =============================================================================
# Hook Step Extraction
# =============================================================================

def extract_step(hook_name: str) -> int:
    """
    Extract step number (0-9) from hook name.

    Hooks are numbered 00-99 with the first digit determining the step.
    Pattern: on_{Model}__{XX}_{description}[.bg].{ext}

    Args:
        hook_name: Hook filename (e.g., 'on_Snapshot__50_wget.py')

    Returns:
        Step number 0-9, or 9 (default) for unnumbered hooks.

    Examples:
        extract_step('on_Snapshot__05_chrome.py') -> 0
        extract_step('on_Snapshot__50_wget.py') -> 5
        extract_step('on_Snapshot__63_media.bg.py') -> 6
        extract_step('on_Snapshot__99_cleanup.sh') -> 9
        extract_step('on_Snapshot__unnumbered.py') -> 9 (default)
    """
    # Pattern matches __XX_ where XX is two digits
    match = re.search(r'__(\d{2})_', hook_name)
    if match:
        two_digit = int(match.group(1))
        step = two_digit // 10  # First digit is the step (0-9)
        return step

    # Log warning for unnumbered hooks and default to step 9
    import sys
    print(f"Warning: Hook '{hook_name}' has no step number (expected __XX_), defaulting to step 9", file=sys.stderr)
    return 9


def is_background_hook(hook_name: str) -> bool:
    """
    Check if a hook is a background hook (doesn't block step advancement).

    Background hooks have '.bg.' in their filename before the extension.

    Args:
        hook_name: Hook filename (e.g., 'on_Snapshot__20_chrome_tab.bg.js')

    Returns:
        True if background hook, False if foreground.

    Examples:
        is_background_hook('on_Snapshot__20_chrome_tab.bg.js') -> True
        is_background_hook('on_Snapshot__50_wget.py') -> False
        is_background_hook('on_Snapshot__63_media.bg.py') -> True
    """
    return '.bg.' in hook_name or '__background' in hook_name


class HookResult(TypedDict, total=False):
    """Raw result from run_hook()."""
    returncode: int
    stdout: str
    stderr: str
    output_json: Optional[Dict[str, Any]]
    output_files: List[str]
    duration_ms: int
    hook: str
    plugin: str  # Plugin name (directory name, e.g., 'wget', 'screenshot')
    hook_name: str  # Full hook filename (e.g., 'on_Snapshot__50_wget.py')
    # New fields for JSONL parsing
    records: List[Dict[str, Any]]  # Parsed JSONL records with 'type' field


def discover_hooks(
    event_name: str,
    filter_disabled: bool = True,
    config: Optional[Dict[str, Any]] = None
) -> List[Path]:
    """
    Find all hook scripts matching on_{event_name}__*.{sh,py,js} pattern.

    Searches both built-in and user plugin directories.
    Filters out hooks from disabled plugins by default (respects USE_/SAVE_ flags).
    Returns scripts sorted alphabetically by filename for deterministic execution order.

    Hook naming convention uses numeric prefixes to control order:
        on_Snapshot__10_title.py        # runs first
        on_Snapshot__15_singlefile.py   # runs second
        on_Snapshot__26_readability.py  # runs later (depends on singlefile)

    Args:
        event_name: Event name (e.g., 'Snapshot', 'Binary', 'Crawl')
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
    hooks = []

    for base_dir in (BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR):
        if not base_dir.exists():
            continue

        # Search for hook scripts in all subdirectories
        for ext in ('sh', 'py', 'js'):
            pattern = f'*/on_{event_name}__*.{ext}'
            hooks.extend(base_dir.glob(pattern))

            # Also check for hooks directly in the plugins directory
            pattern_direct = f'on_{event_name}__*.{ext}'
            hooks.extend(base_dir.glob(pattern_direct))

    # Filter by enabled plugins
    if filter_disabled:
        # Get merged config if not provided (lazy import to avoid circular dependency)
        if config is None:
            from archivebox.config.configset import get_config
            config = get_config(scope='global')

        enabled_hooks = []

        for hook in hooks:
            # Get plugin name from parent directory
            # e.g., archivebox/plugins/wget/on_Snapshot__50_wget.py -> 'wget'
            plugin_name = hook.parent.name

            # Check if this is a plugin directory (not the root plugins dir)
            if plugin_name in ('plugins', '.'):
                # Hook is in root plugins directory, not a plugin subdir
                # Include it by default (no filtering for non-plugin hooks)
                enabled_hooks.append(hook)
                continue

            # Check if plugin is enabled
            plugin_config = get_plugin_special_config(plugin_name, config)
            if plugin_config['enabled']:
                enabled_hooks.append(hook)

        hooks = enabled_hooks

    # Sort by filename (not full path) to ensure numeric prefix ordering works
    # e.g., on_Snapshot__10_title.py sorts before on_Snapshot__26_readability.py
    return sorted(set(hooks), key=lambda p: p.name)


def run_hook(
    script: Path,
    output_dir: Path,
    config: Dict[str, Any],
    timeout: Optional[int] = None,
    **kwargs: Any
) -> HookResult:
    """
    Execute a hook script with the given arguments.

    This is the low-level hook executor. For running extractors with proper
    metadata handling, use call_extractor() instead.

    Config is passed to hooks via environment variables. Caller MUST use
    get_config() to merge all sources (file, env, machine, crawl, snapshot).

    Args:
        script: Path to the hook script (.sh, .py, or .js)
        output_dir: Working directory for the script (where output files go)
        config: Merged config dict from get_config(crawl=..., snapshot=...) - REQUIRED
        timeout: Maximum execution time in seconds
                 If None, auto-detects from PLUGINNAME_TIMEOUT config (fallback to TIMEOUT, default 300)
        **kwargs: Arguments passed to the script as --key=value

    Returns:
        HookResult with 'returncode', 'stdout', 'stderr', 'output_json', 'output_files', 'duration_ms'

    Example:
        from archivebox.config.configset import get_config
        config = get_config(crawl=my_crawl, snapshot=my_snapshot)
        result = run_hook(hook_path, output_dir, config=config, url=url, snapshot_id=id)
    """
    import time
    start_time = time.time()

    # Auto-detect timeout from plugin config if not explicitly provided
    if timeout is None:
        plugin_name = script.parent.name
        plugin_config = get_plugin_special_config(plugin_name, config)
        timeout = plugin_config['timeout']

    if not script.exists():
        return HookResult(
            returncode=1,
            stdout='',
            stderr=f'Hook script not found: {script}',
            output_json=None,
            output_files=[],
            duration_ms=0,
            hook=str(script),
            plugin=script.parent.name,
            hook_name=script.name,
        )

    # Determine the interpreter based on file extension
    ext = script.suffix.lower()
    if ext == '.sh':
        cmd = ['bash', str(script)]
    elif ext == '.py':
        cmd = ['python3', str(script)]
    elif ext == '.js':
        cmd = ['node', str(script)]
    else:
        # Try to execute directly (assumes shebang)
        cmd = [str(script)]

    # Build CLI arguments from kwargs
    for key, value in kwargs.items():
        # Skip keys that start with underscore (internal parameters)
        if key.startswith('_'):
            continue

        arg_key = f'--{key.replace("_", "-")}'
        if isinstance(value, bool):
            if value:
                cmd.append(arg_key)
        elif value is not None and value != '':
            # JSON-encode complex values, use str for simple ones
            # Skip empty strings to avoid --key= which breaks argument parsers
            if isinstance(value, (dict, list)):
                cmd.append(f'{arg_key}={json.dumps(value)}')
            else:
                # Ensure value is converted to string and strip whitespace
                str_value = str(value).strip()
                if str_value:  # Only add if non-empty after stripping
                    cmd.append(f'{arg_key}={str_value}')

    # Set up environment with base paths
    env = os.environ.copy()
    env['DATA_DIR'] = str(getattr(settings, 'DATA_DIR', Path.cwd()))
    env['ARCHIVE_DIR'] = str(getattr(settings, 'ARCHIVE_DIR', Path.cwd() / 'archive'))
    env.setdefault('MACHINE_ID', getattr(settings, 'MACHINE_ID', '') or os.environ.get('MACHINE_ID', ''))

    # Use Machine.config.PATH if set (includes pip/npm bin dirs from providers)
    try:
        from archivebox.machine.models import Machine
        machine = Machine.current()
        if machine and machine.config:
            machine_path = machine.config.get('config/PATH')
            if machine_path:
                env['PATH'] = machine_path
            # Also set NODE_MODULES_DIR if configured
            node_modules_dir = machine.config.get('config/NODE_MODULES_DIR')
            if node_modules_dir:
                env['NODE_MODULES_DIR'] = node_modules_dir
    except Exception:
        pass  # Fall back to system PATH if Machine not available

    # Export all config values to environment (already merged by get_config())
    for key, value in config.items():
        if value is None:
            continue
        elif isinstance(value, bool):
            env[key] = 'true' if value else 'false'
        elif isinstance(value, (list, dict)):
            env[key] = json.dumps(value)
        else:
            env[key] = str(value)

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    # Capture files before execution to detect new output
    files_before = set(output_dir.rglob('*')) if output_dir.exists() else set()

    # Detect if this is a background hook (long-running daemon)
    # New convention: .bg. suffix (e.g., on_Snapshot__21_consolelog.bg.js)
    # Old convention: __background in stem (for backwards compatibility)
    is_background = '.bg.' in script.name or '__background' in script.stem

    # Set up output files for ALL hooks - use hook-specific names to avoid conflicts
    # when multiple hooks run in the same plugin directory
    # e.g., on_Snapshot__20_chrome_tab.bg.js -> on_Snapshot__20_chrome_tab.bg.stdout.log
    hook_basename = script.stem  # e.g., "on_Snapshot__20_chrome_tab.bg"
    stdout_file = output_dir / f'{hook_basename}.stdout.log'
    stderr_file = output_dir / f'{hook_basename}.stderr.log'
    pid_file = output_dir / f'{hook_basename}.pid'
    cmd_file = output_dir / f'{hook_basename}.sh'

    try:
        # Write command script for validation
        from archivebox.misc.process_utils import write_cmd_file
        write_cmd_file(cmd_file, cmd)

        # Open log files for writing
        with open(stdout_file, 'w') as out, open(stderr_file, 'w') as err:
            process = subprocess.Popen(
                cmd,
                cwd=str(output_dir),
                stdout=out,
                stderr=err,
                env=env,
            )

            # Write PID with mtime set to process start time for validation
            from archivebox.misc.process_utils import write_pid_file_with_mtime
            process_start_time = time.time()
            write_pid_file_with_mtime(pid_file, process.pid, process_start_time)

            if is_background:
                # Background hook - return None immediately, don't wait
                # Process continues running, writing to stdout.log
                # ArchiveResult will poll for completion later
                return None

            # Normal hook - wait for completion with timeout
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()  # Clean up zombie
                duration_ms = int((time.time() - start_time) * 1000)
                return HookResult(
                    returncode=-1,
                    stdout='',
                    stderr=f'Hook timed out after {timeout} seconds',
                    output_json=None,
                    output_files=[],
                    duration_ms=duration_ms,
                    hook=str(script),
                )

        # Read output from files
        stdout = stdout_file.read_text() if stdout_file.exists() else ''
        stderr = stderr_file.read_text() if stderr_file.exists() else ''

        # Detect new files created by the hook
        files_after = set(output_dir.rglob('*')) if output_dir.exists() else set()
        new_files = [str(f.relative_to(output_dir)) for f in (files_after - files_before) if f.is_file()]
        # Exclude the log/pid/sh files themselves from new_files (hook-specific names)
        hook_output_files = {
            f'{hook_basename}.stdout.log',
            f'{hook_basename}.stderr.log',
            f'{hook_basename}.pid',
            f'{hook_basename}.sh',
        }
        new_files = [f for f in new_files if f not in hook_output_files]

        # Parse JSONL output from stdout
        # Each line starting with { that has 'type' field is a record
        records = []
        plugin_name = script.parent.name  # Plugin directory name (e.g., 'wget')
        hook_name = script.name  # Full hook filename (e.g., 'on_Snapshot__50_wget.py')

        for line in stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith('{'):
                continue

            try:
                data = json.loads(line)
                if 'type' in data:
                    # Add plugin metadata to every record
                    data['plugin'] = plugin_name
                    data['hook_name'] = hook_name
                    data['plugin_hook'] = str(script)
                    records.append(data)
            except json.JSONDecodeError:
                pass

        duration_ms = int((time.time() - start_time) * 1000)

        # Clean up log files on success (keep on failure for debugging)
        if returncode == 0:
            stdout_file.unlink(missing_ok=True)
            stderr_file.unlink(missing_ok=True)
            pid_file.unlink(missing_ok=True)

        return HookResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            output_json=output_json,
            output_files=new_files,
            duration_ms=duration_ms,
            hook=str(script),
            plugin=plugin_name,
            hook_name=hook_name,
            records=records,
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        return HookResult(
            returncode=-1,
            stdout='',
            stderr=f'Failed to run hook: {type(e).__name__}: {e}',
            output_json=None,
            output_files=[],
            duration_ms=duration_ms,
            hook=str(script),
            plugin=script.parent.name,
            hook_name=script.name,
            records=[],
        )


def collect_urls_from_plugins(snapshot_dir: Path) -> List[Dict[str, Any]]:
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

        urls_file = subdir / 'urls.jsonl'
        if not urls_file.exists():
            continue

        try:
            with open(urls_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            if entry.get('url'):
                                # Track which parser plugin found this URL
                                entry['plugin'] = subdir.name
                                urls.append(entry)
                        except json.JSONDecodeError:
                            continue
        except Exception:
            pass

    return urls


def run_hooks(
    event_name: str,
    output_dir: Path,
    config: Dict[str, Any],
    timeout: Optional[int] = None,
    stop_on_failure: bool = False,
    **kwargs: Any
) -> List[HookResult]:
    """
    Run all hooks for a given event.

    Args:
        event_name: The event name to trigger (e.g., 'Snapshot', 'Crawl', 'Binary')
        output_dir: Working directory for hook scripts
        config: Merged config dict from get_config(crawl=..., snapshot=...) - REQUIRED
        timeout: Maximum execution time per hook (None = auto-detect from plugin config)
        stop_on_failure: If True, stop executing hooks after first failure
        **kwargs: Arguments passed to each hook script

    Returns:
        List of results from each hook execution

    Example:
        from archivebox.config.configset import get_config
        config = get_config(crawl=my_crawl, snapshot=my_snapshot)
        results = run_hooks('Snapshot', output_dir, config=config, url=url, snapshot_id=id)
    """
    hooks = discover_hooks(event_name, config=config)
    results = []

    for hook in hooks:
        result = run_hook(hook, output_dir, config=config, timeout=timeout, **kwargs)

        # Background hooks return None - skip adding to results
        if result is None:
            continue

        result['hook'] = str(hook)
        results.append(result)

        if stop_on_failure and result['returncode'] != 0:
            break

    return results


def get_plugins() -> List[str]:
    """
    Get list of available plugins by discovering Snapshot hooks.

    Returns plugin names (directory names) that contain on_Snapshot hooks.
    The plugin name is the plugin directory name, not the hook script name.

    Example:
    archivebox/plugins/chrome_session/on_Snapshot__20_chrome_tab.bg.js
    -> plugin = 'chrome_session'

    Sorted alphabetically (plugins control their hook order via numeric prefixes in hook names).
    """
    plugins = []

    for base_dir in (BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR):
        if not base_dir.exists():
            continue

        for ext in ('sh', 'py', 'js'):
            for hook_path in base_dir.glob(f'*/on_Snapshot__*.{ext}'):
                # Use plugin directory name as plugin name
                plugin_name = hook_path.parent.name
                plugins.append(plugin_name)

    return sorted(set(plugins))


def get_parser_plugins() -> List[str]:
    """
    Get list of parser plugins by discovering parse_*_urls hooks.

    Parser plugins discover URLs from source files and output urls.jsonl.
    Returns plugin names like: ['50_parse_html_urls', '51_parse_rss_urls', ...]
    """
    return [e for e in get_plugins() if 'parse_' in e and '_urls' in e]


def get_plugin_name(plugin: str) -> str:
    """
    Get the base plugin name without numeric prefix.

    Examples:
        '10_title' -> 'title'
        '26_readability' -> 'readability'
        '50_parse_html_urls' -> 'parse_html_urls'
    """
    # Split on first underscore after any leading digits
    parts = plugin.split('_', 1)
    if len(parts) == 2 and parts[0].isdigit():
        return parts[1]
    return plugin


def is_parser_plugin(plugin: str) -> bool:
    """Check if a plugin is a parser plugin (discovers URLs)."""
    name = get_plugin_name(plugin)
    return name.startswith('parse_') and name.endswith('_urls')


def get_enabled_plugins(config: Optional[Dict[str, Any]] = None) -> List[str]:
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
        config = get_config(scope='global')

    # Support explicit ENABLED_PLUGINS override (legacy)
    if 'ENABLED_PLUGINS' in config:
        return config['ENABLED_PLUGINS']
    if 'ENABLED_EXTRACTORS' in config:
        return config['ENABLED_EXTRACTORS']

    # Filter all plugins by enabled status
    all_plugins = get_plugins()
    enabled = []

    for plugin in all_plugins:
        plugin_config = get_plugin_special_config(plugin, config)
        if plugin_config['enabled']:
            enabled.append(plugin)

    return enabled


def discover_plugins_that_provide_interface(
    module_name: str,
    required_attrs: List[str],
    plugin_prefix: Optional[str] = None,
) -> Dict[str, Any]:
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
            module_path = plugin_dir / f'{module_name}.py'
            if not module_path.exists():
                continue

            try:
                # Import the module dynamically
                spec = importlib.util.spec_from_file_location(
                    f'archivebox.plugins.{plugin_name}.{module_name}',
                    module_path
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
                    backend_name = plugin_name[len(plugin_prefix):]
                else:
                    backend_name = plugin_name

                backends[backend_name] = module

            except Exception:
                # Skip plugins that fail to import
                continue

    return backends


def get_search_backends() -> Dict[str, Any]:
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
        module_name='search',
        required_attrs=['search', 'flush'],
        plugin_prefix='search_backend_',
    )


def discover_plugin_configs() -> Dict[str, Dict[str, Any]]:
    """
    Discover all plugin config.json schemas.

    Each plugin can define a config.json file with JSONSchema defining
    its configuration options. This function discovers and loads all such schemas.

    The config.json files use JSONSchema draft-07 with custom extensions:
        - x-fallback: Global config key to use as fallback
        - x-aliases: List of old/alternative config key names

    Returns:
        Dict mapping plugin names to their parsed JSONSchema configs.
        e.g., {'wget': {...schema...}, 'chrome_session': {...schema...}}

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

    for base_dir in (BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR):
        if not base_dir.exists():
            continue

        for plugin_dir in base_dir.iterdir():
            if not plugin_dir.is_dir():
                continue

            config_path = plugin_dir / 'config.json'
            if not config_path.exists():
                continue

            try:
                with open(config_path, 'r') as f:
                    schema = json.load(f)

                # Basic validation: must be an object with properties
                if not isinstance(schema, dict):
                    continue
                if schema.get('type') != 'object':
                    continue
                if 'properties' not in schema:
                    continue

                configs[plugin_dir.name] = schema

            except (json.JSONDecodeError, OSError) as e:
                # Log warning but continue - malformed config shouldn't break discovery
                import sys
                print(f"Warning: Failed to load config.json from {plugin_dir.name}: {e}", file=sys.stderr)
                continue

    return configs


def get_config_defaults_from_plugins() -> Dict[str, Any]:
    """
    Get default values for all plugin config options.

    Returns:
        Dict mapping config keys to their default values.
        e.g., {'SAVE_WGET': True, 'WGET_TIMEOUT': 60, ...}
    """
    plugin_configs = discover_plugin_configs()
    defaults = {}

    for plugin_name, schema in plugin_configs.items():
        properties = schema.get('properties', {})
        for key, prop_schema in properties.items():
            if 'default' in prop_schema:
                defaults[key] = prop_schema['default']

    return defaults


def get_plugin_special_config(plugin_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
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

    # 1. Enabled: PLUGINNAME_ENABLED (default True)
    # Old names (USE_*, SAVE_*) are aliased in config.json via x-aliases
    enabled_key = f'{plugin_upper}_ENABLED'
    enabled = config.get(enabled_key)
    if enabled is None:
        enabled = True
    elif isinstance(enabled, str):
        # Handle string values from config file ("true"/"false")
        enabled = enabled.lower() not in ('false', '0', 'no', '')

    # 2. Timeout: PLUGINNAME_TIMEOUT (fallback to TIMEOUT, default 300)
    timeout_key = f'{plugin_upper}_TIMEOUT'
    timeout = config.get(timeout_key) or config.get('TIMEOUT', 300)

    # 3. Binary: PLUGINNAME_BINARY (default to plugin_name)
    binary_key = f'{plugin_upper}_BINARY'
    binary = config.get(binary_key, plugin_name)

    return {
        'enabled': bool(enabled),
        'timeout': int(timeout),
        'binary': str(binary),
    }


# =============================================================================
# Plugin Template Discovery
# =============================================================================
#
# Plugins can provide custom templates for rendering their output in the UI.
# Templates are discovered by filename convention inside each plugin's templates/ dir:
#
#     archivebox/plugins/<plugin_name>/
#         templates/
#             icon.html          # Icon for admin table view (small inline HTML)
#             thumbnail.html     # Preview thumbnail for snapshot cards
#             embed.html         # Iframe embed content for main preview
#             fullscreen.html    # Fullscreen view template
#
# Template context variables available:
#     {{ result }}         - ArchiveResult object
#     {{ snapshot }}       - Parent Snapshot object
#     {{ output_path }}    - Path to output file/dir relative to snapshot dir
#     {{ plugin }}         - Plugin name (e.g., 'screenshot', 'singlefile')
#

# Default templates used when plugin doesn't provide one
DEFAULT_TEMPLATES = {
    'icon': '''<span title="{{ plugin }}">{{ icon }}</span>''',
    'thumbnail': '''
        <img src="{{ output_path }}"
             alt="{{ plugin }} output"
             style="max-width: 100%; max-height: 100px; object-fit: cover;"
             onerror="this.style.display='none'">
    ''',
    'embed': '''
        <iframe src="{{ output_path }}"
                style="width: 100%; height: 100%; border: none;"
                sandbox="allow-same-origin allow-scripts">
        </iframe>
    ''',
    'fullscreen': '''
        <iframe src="{{ output_path }}"
                style="width: 100%; height: 100vh; border: none;"
                sandbox="allow-same-origin allow-scripts allow-forms">
        </iframe>
    ''',
}


def get_plugin_template(plugin: str, template_name: str, fallback: bool = True) -> Optional[str]:
    """
    Get a plugin template by plugin name and template type.

    Args:
        plugin: Plugin name (e.g., 'screenshot', '15_singlefile')
        template_name: One of 'icon', 'thumbnail', 'embed', 'fullscreen'
        fallback: If True, return default template if plugin template not found

    Returns:
        Template content as string, or None if not found and fallback=False.
    """
    base_name = get_plugin_name(plugin)

    for base_dir in (BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR):
        if not base_dir.exists():
            continue

        # Look for plugin directory matching plugin name
        for plugin_dir in base_dir.iterdir():
            if not plugin_dir.is_dir():
                continue

            # Match by directory name (exact or partial)
            if plugin_dir.name == base_name or plugin_dir.name.endswith(f'_{base_name}'):
                template_path = plugin_dir / 'templates' / f'{template_name}.html'
                if template_path.exists():
                    return template_path.read_text()

    # Fall back to default template if requested
    if fallback:
        return DEFAULT_TEMPLATES.get(template_name, '')

    return None


def get_plugin_icon(plugin: str) -> str:
    """
    Get the icon for a plugin from its icon.html template.

    Args:
        plugin: Plugin name (e.g., 'screenshot', '15_singlefile')

    Returns:
        Icon HTML/emoji string.
    """
    # Try plugin-provided icon template
    icon_template = get_plugin_template(plugin, 'icon', fallback=False)
    if icon_template:
        return icon_template.strip()

    # Fall back to generic folder icon
    return '📁'


def get_all_plugin_icons() -> Dict[str, str]:
    """
    Get icons for all discovered plugins.

    Returns:
        Dict mapping plugin base names to their icons.
    """
    icons = {}
    for plugin in get_plugins():
        base_name = get_plugin_name(plugin)
        icons[base_name] = get_plugin_icon(plugin)
    return icons


def discover_plugin_templates() -> Dict[str, Dict[str, str]]:
    """
    Discover all plugin templates organized by plugin.

    Returns:
        Dict mapping plugin names to dicts of template_name -> template_path.
        e.g., {'screenshot': {'icon': '/path/to/icon.html', 'thumbnail': '/path/to/thumbnail.html'}}
    """
    templates: Dict[str, Dict[str, str]] = {}

    for base_dir in (BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR):
        if not base_dir.exists():
            continue

        for plugin_dir in base_dir.iterdir():
            if not plugin_dir.is_dir():
                continue

            templates_dir = plugin_dir / 'templates'
            if not templates_dir.exists():
                continue

            plugin_templates = {}
            for template_file in templates_dir.glob('*.html'):
                template_name = template_file.stem  # icon, thumbnail, embed, fullscreen
                plugin_templates[template_name] = str(template_file)

            if plugin_templates:
                templates[plugin_dir.name] = plugin_templates

    return templates


# =============================================================================
# Hook Result Processing Helpers
# =============================================================================


def find_binary_for_cmd(cmd: List[str], machine_id: str) -> Optional[str]:
    """
    Find Binary for a command, trying abspath first then name.
    Only matches binaries on the current machine.

    Args:
        cmd: Command list (e.g., ['/usr/bin/wget', '-p', 'url'])
        machine_id: Current machine ID

    Returns:
        Binary ID as string if found, None otherwise
    """
    if not cmd:
        return None

    from archivebox.machine.models import Binary

    bin_path_or_name = cmd[0] if isinstance(cmd, list) else cmd

    # Try matching by absolute path first
    binary = Binary.objects.filter(
        abspath=bin_path_or_name,
        machine_id=machine_id
    ).first()

    if binary:
        return str(binary.id)

    # Fallback: match by binary name
    bin_name = Path(bin_path_or_name).name
    binary = Binary.objects.filter(
        name=bin_name,
        machine_id=machine_id
    ).first()

    return str(binary.id) if binary else None


def create_model_record(record: Dict[str, Any]) -> Any:
    """
    Generic helper to create/update model instances from hook JSONL output.

    Args:
        record: Dict with 'type' field and model data

    Returns:
        Created/updated model instance, or None if type unknown
    """
    from archivebox.machine.models import Binary, Machine

    record_type = record.pop('type', None)
    if not record_type:
        return None

    # Remove plugin metadata (not model fields)
    record.pop('plugin', None)
    record.pop('plugin_hook', None)

    if record_type == 'Binary':
        # Binary requires machine FK
        machine = Machine.current()
        record.setdefault('machine', machine)

        # Required fields check
        name = record.get('name')
        abspath = record.get('abspath')
        if not name or not abspath:
            return None

        obj, created = Binary.objects.update_or_create(
            machine=machine,
            name=name,
            defaults={
                'abspath': abspath,
                'version': record.get('version', ''),
                'sha256': record.get('sha256', ''),
                'binprovider': record.get('binprovider', 'env'),
            }
        )
        return obj

    elif record_type == 'Machine':
        # Machine config update (special _method handling)
        method = record.pop('_method', None)
        if method == 'update':
            key = record.get('key')
            value = record.get('value')
            if key and value:
                machine = Machine.current()
                if not machine.config:
                    machine.config = {}
                machine.config[key] = value
                machine.save(update_fields=['config'])
                return machine
        return None

    # Add more types as needed (Dependency, Snapshot, etc.)
    else:
        # Unknown type - log warning but don't fail
        import sys
        print(f"Warning: Unknown record type '{record_type}' from hook output", file=sys.stderr)
        return None


def process_hook_records(records: List[Dict[str, Any]], overrides: Dict[str, Any] = None) -> Dict[str, int]:
    """
    Process JSONL records from hook output.

    Uses Model.from_jsonl() which automatically filters by JSONL_TYPE.
    Each model only processes records matching its type.

    Args:
        records: List of JSONL record dicts from result['records']
        overrides: Dict with 'snapshot', 'crawl', 'dependency', 'created_by_id', etc.

    Returns:
        Dict with counts by record type
    """
    from archivebox.core.models import Snapshot, Tag
    from archivebox.machine.models import Binary, Machine

    overrides = overrides or {}

    # Filter out ArchiveResult records (they update the calling AR, not create new ones)
    filtered_records = [r for r in records if r.get('type') != 'ArchiveResult']

    # Each model's from_jsonl() filters to only its own type
    snapshots = Snapshot.from_jsonl(filtered_records, overrides)
    tags = Tag.from_jsonl(filtered_records, overrides)
    binaries = Binary.from_jsonl(filtered_records, overrides)
    machines = Machine.from_jsonl(filtered_records, overrides)

    return {
        'Snapshot': len(snapshots),
        'Tag': len(tags),
        'Binary': len(binaries),
        'Machine': len(machines),
    }


def process_is_alive(pid_file: Path) -> bool:
    """
    Check if process in PID file is still running.

    Args:
        pid_file: Path to hook.pid file

    Returns:
        True if process is alive, False otherwise
    """
    if not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # Signal 0 = check if process exists without killing it
        return True
    except (OSError, ValueError):
        return False


def kill_process(pid_file: Path, sig: int = signal.SIGTERM, validate: bool = True):
    """
    Kill process in PID file with optional validation.

    Args:
        pid_file: Path to hook-specific .pid file (e.g., on_Snapshot__20_chrome_tab.bg.pid)
        sig: Signal to send (default SIGTERM)
        validate: If True, validate process identity before killing (default: True)
    """
    from archivebox.misc.process_utils import safe_kill_process

    if validate:
        # Use safe kill with validation
        # Derive cmd file from pid file: on_Snapshot__20_chrome_tab.bg.pid -> on_Snapshot__20_chrome_tab.bg.sh
        cmd_file = pid_file.with_suffix('.sh')
        safe_kill_process(pid_file, cmd_file, signal_num=sig)
    else:
        # Legacy behavior - kill without validation
        if not pid_file.exists():
            return
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, sig)
        except (OSError, ValueError):
            pass


