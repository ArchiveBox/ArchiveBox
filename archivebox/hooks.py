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
    - Extractors run sequentially within each Snapshot (ordered by numeric prefix)
    - Multiple Snapshots can process in parallel
    - Failed extractors don't block subsequent extractors

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
"""

__package__ = 'archivebox'

import os
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


def discover_hooks(event_name: str) -> List[Path]:
    """
    Find all hook scripts matching on_{event_name}__*.{sh,py,js} pattern.

    Searches both built-in and user plugin directories.
    Returns scripts sorted alphabetically by filename for deterministic execution order.

    Hook naming convention uses numeric prefixes to control order:
        on_Snapshot__10_title.py        # runs first
        on_Snapshot__15_singlefile.py   # runs second
        on_Snapshot__26_readability.py  # runs later (depends on singlefile)

    Example:
        discover_hooks('Snapshot')
        # Returns: [Path('.../on_Snapshot__10_title.py'), Path('.../on_Snapshot__15_singlefile.py'), ...]
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

    # Sort by filename (not full path) to ensure numeric prefix ordering works
    # e.g., on_Snapshot__10_title.py sorts before on_Snapshot__26_readability.py
    return sorted(set(hooks), key=lambda p: p.name)


def discover_all_hooks() -> Dict[str, List[Path]]:
    """
    Discover all hooks organized by event name.

    Returns a dict mapping event names to lists of hook script paths.
    """
    hooks_by_event: Dict[str, List[Path]] = {}

    for base_dir in (BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR):
        if not base_dir.exists():
            continue

        for ext in ('sh', 'py', 'js'):
            for hook_path in base_dir.glob(f'*/on_*__*.{ext}'):
                # Extract event name from filename: on_EventName__hook_name.ext
                filename = hook_path.stem  # on_EventName__hook_name
                if filename.startswith('on_') and '__' in filename:
                    event_name = filename[3:].split('__')[0]  # EventName
                    if event_name not in hooks_by_event:
                        hooks_by_event[event_name] = []
                    hooks_by_event[event_name].append(hook_path)

    # Sort hooks within each event
    for event_name in hooks_by_event:
        hooks_by_event[event_name] = sorted(set(hooks_by_event[event_name]), key=lambda p: p.name)

    return hooks_by_event


def run_hook(
    script: Path,
    output_dir: Path,
    timeout: int = 300,
    config_objects: Optional[List[Any]] = None,
    **kwargs: Any
) -> HookResult:
    """
    Execute a hook script with the given arguments.

    This is the low-level hook executor. For running extractors with proper
    metadata handling, use call_extractor() instead.

    Config is passed to hooks via environment variables with this priority:
    1. Plugin schema defaults (config.json)
    2. Config file (ArchiveBox.conf)
    3. Environment variables
    4. Machine.config (auto-included, lowest override priority)
    5. config_objects (in order - later objects override earlier ones)

    Args:
        script: Path to the hook script (.sh, .py, or .js)
        output_dir: Working directory for the script (where output files go)
        timeout: Maximum execution time in seconds
        config_objects: Optional list of objects with .config JSON fields
                       (e.g., [crawl, snapshot] - later items have higher priority)
        **kwargs: Arguments passed to the script as --key=value

    Returns:
        HookResult with 'returncode', 'stdout', 'stderr', 'output_json', 'output_files', 'duration_ms'
    """
    import time
    start_time = time.time()

    # Auto-include Machine.config at the start (lowest priority among config_objects)
    from machine.models import Machine
    machine = Machine.current()
    all_config_objects = [machine] + list(config_objects or [])

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

    # If a Crawl is in config_objects, pass its OUTPUT_DIR for hooks that need to find crawl-level resources
    for obj in all_config_objects:
        if hasattr(obj, 'OUTPUT_DIR') and hasattr(obj, 'get_urls_list'):  # Duck-type check for Crawl
            env['CRAWL_OUTPUT_DIR'] = str(obj.OUTPUT_DIR)
            break

    # Build overrides from any objects with .config fields (in order, later overrides earlier)
    # all_config_objects includes Machine at the start, then any passed config_objects
    overrides = {}
    for obj in all_config_objects:
        if obj and hasattr(obj, 'config') and obj.config:
            # Strip 'config/' prefix from Machine.config keys (e.g., 'config/CHROME_BINARY' -> 'CHROME_BINARY')
            for key, value in obj.config.items():
                clean_key = key.removeprefix('config/')
                overrides[clean_key] = value

    # Get plugin config from JSON schemas with hierarchy resolution
    # This merges: schema defaults -> config file -> env vars -> object config overrides
    plugin_config = get_flat_plugin_config(overrides=overrides if overrides else None)
    export_plugin_config_to_env(plugin_config, env)

    # Also pass core config values that aren't in plugin schemas yet
    # These are legacy values that may still be needed
    from archivebox import config
    env.setdefault('CHROME_BINARY', str(getattr(config, 'CHROME_BINARY', '')))
    env.setdefault('WGET_BINARY', str(getattr(config, 'WGET_BINARY', '')))
    env.setdefault('CURL_BINARY', str(getattr(config, 'CURL_BINARY', '')))
    env.setdefault('GIT_BINARY', str(getattr(config, 'GIT_BINARY', '')))
    env.setdefault('YOUTUBEDL_BINARY', str(getattr(config, 'YOUTUBEDL_BINARY', '')))
    env.setdefault('SINGLEFILE_BINARY', str(getattr(config, 'SINGLEFILE_BINARY', '')))
    env.setdefault('READABILITY_BINARY', str(getattr(config, 'READABILITY_BINARY', '')))
    env.setdefault('MERCURY_BINARY', str(getattr(config, 'MERCURY_BINARY', '')))
    env.setdefault('NODE_BINARY', str(getattr(config, 'NODE_BINARY', '')))
    env.setdefault('TIMEOUT', str(getattr(config, 'TIMEOUT', 60)))
    env.setdefault('CHECK_SSL_VALIDITY', str(getattr(config, 'CHECK_SSL_VALIDITY', True)))
    env.setdefault('USER_AGENT', str(getattr(config, 'USER_AGENT', '')))
    env.setdefault('RESOLUTION', str(getattr(config, 'RESOLUTION', '')))

    # Pass SEARCH_BACKEND_ENGINE from new-style config
    try:
        from archivebox.config.configset import get_config
        search_config = get_config()
        env.setdefault('SEARCH_BACKEND_ENGINE', str(search_config.get('SEARCH_BACKEND_ENGINE', 'ripgrep')))
    except Exception:
        env.setdefault('SEARCH_BACKEND_ENGINE', 'ripgrep')

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    # Capture files before execution to detect new output
    files_before = set(output_dir.rglob('*')) if output_dir.exists() else set()

    # Detect if this is a background hook (long-running daemon)
    # New convention: .bg. suffix (e.g., on_Snapshot__21_consolelog.bg.js)
    # Old convention: __background in stem (for backwards compatibility)
    is_background = '.bg.' in script.name or '__background' in script.stem

    # Set up output files for ALL hooks (useful for debugging)
    stdout_file = output_dir / 'stdout.log'
    stderr_file = output_dir / 'stderr.log'
    pid_file = output_dir / 'hook.pid'
    cmd_file = output_dir / 'cmd.sh'

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
        # Exclude the log files themselves from new_files
        new_files = [f for f in new_files if f not in ('stdout.log', 'stderr.log', 'hook.pid')]

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
    timeout: int = 300,
    stop_on_failure: bool = False,
    config_objects: Optional[List[Any]] = None,
    **kwargs: Any
) -> List[HookResult]:
    """
    Run all hooks for a given event.

    Args:
        event_name: The event name to trigger (e.g., 'Snapshot__wget')
        output_dir: Working directory for hook scripts
        timeout: Maximum execution time per hook
        stop_on_failure: If True, stop executing hooks after first failure
        config_objects: Optional list of objects with .config JSON fields
                       (e.g., [crawl, snapshot] - later items have higher priority)
        **kwargs: Arguments passed to each hook script

    Returns:
        List of results from each hook execution
    """
    hooks = discover_hooks(event_name)
    results = []

    for hook in hooks:
        result = run_hook(hook, output_dir, timeout=timeout, config_objects=config_objects, **kwargs)

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


# Precedence order for search indexing (lower number = higher priority)
# Used to select which plugin's output to use for full-text search
# Plugin names here should match the part after the numeric prefix
# e.g., '31_readability' -> 'readability'
EXTRACTOR_INDEXING_PRECEDENCE = [
    ('readability', 1),
    ('mercury', 2),
    ('htmltotext', 3),
    ('singlefile', 4),
    ('dom', 5),
    ('wget', 6),
]


def get_enabled_plugins(config: Optional[Dict] = None) -> List[str]:
    """
    Get the list of enabled plugins based on config and available hooks.

    Checks for ENABLED_PLUGINS (or legacy ENABLED_EXTRACTORS) in config,
    falls back to discovering available hooks from the plugins directory.

    Returns plugin names sorted alphabetically (numeric prefix controls order).
    """
    if config:
        # Support both new and legacy config keys
        if 'ENABLED_PLUGINS' in config:
            return config['ENABLED_PLUGINS']
        if 'ENABLED_EXTRACTORS' in config:
            return config['ENABLED_EXTRACTORS']

    # Discover from hooks - this is the source of truth
    return get_plugins()


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


def get_merged_config_schema() -> Dict[str, Any]:
    """
    Get a merged JSONSchema combining all plugin config schemas.

    This creates a single schema that can validate all plugin config keys.
    Useful for validating the complete configuration at startup.

    Returns:
        Combined JSONSchema with all plugin properties merged.
    """
    plugin_configs = discover_plugin_configs()

    merged_properties = {}
    for plugin_name, schema in plugin_configs.items():
        properties = schema.get('properties', {})
        for key, prop_schema in properties.items():
            if key in merged_properties:
                # Key already exists from another plugin - log warning but keep first
                import sys
                print(f"Warning: Config key '{key}' defined in multiple plugins, using first definition", file=sys.stderr)
                continue
            merged_properties[key] = prop_schema

    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "additionalProperties": True,  # Allow unknown keys (core config, etc.)
        "properties": merged_properties,
    }


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


def resolve_config_value(
    key: str,
    prop_schema: Dict[str, Any],
    env_vars: Dict[str, str],
    config_file: Dict[str, str],
    overrides: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Resolve a single config value following the hierarchy and schema rules.

    Resolution order (later overrides earlier):
        1. Schema default
        2. x-fallback (global config key)
        3. Config file (ArchiveBox.conf)
        4. Environment variables (including x-aliases)
        5. Explicit overrides (User/Crawl/Snapshot config)

    Args:
        key: Config key name (e.g., 'WGET_TIMEOUT')
        prop_schema: JSONSchema property definition for this key
        env_vars: Environment variables dict
        config_file: Config file values dict
        overrides: Optional override values (from User/Crawl/Snapshot)

    Returns:
        Resolved value with appropriate type coercion.
    """
    value = None
    prop_type = prop_schema.get('type', 'string')

    # 1. Start with schema default
    if 'default' in prop_schema:
        value = prop_schema['default']

    # 2. Check x-fallback (global config key)
    fallback_key = prop_schema.get('x-fallback')
    if fallback_key:
        if fallback_key in env_vars:
            value = env_vars[fallback_key]
        elif fallback_key in config_file:
            value = config_file[fallback_key]

    # 3. Check config file for main key
    if key in config_file:
        value = config_file[key]

    # 4. Check environment variables (main key and aliases)
    keys_to_check = [key] + prop_schema.get('x-aliases', [])
    for check_key in keys_to_check:
        if check_key in env_vars:
            value = env_vars[check_key]
            break

    # 5. Apply explicit overrides
    if overrides and key in overrides:
        value = overrides[key]

    # Type coercion for env var strings
    if value is not None and isinstance(value, str):
        value = coerce_config_value(value, prop_type, prop_schema)

    return value


def coerce_config_value(value: str, prop_type: str, prop_schema: Dict[str, Any]) -> Any:
    """
    Coerce a string value to the appropriate type based on schema.

    Args:
        value: String value to coerce
        prop_type: JSONSchema type ('boolean', 'integer', 'number', 'array', 'string')
        prop_schema: Full property schema (for array item types, etc.)

    Returns:
        Coerced value of appropriate type.
    """
    if prop_type == 'boolean':
        return value.lower() in ('true', '1', 'yes', 'on')
    elif prop_type == 'integer':
        try:
            return int(value)
        except ValueError:
            return prop_schema.get('default', 0)
    elif prop_type == 'number':
        try:
            return float(value)
        except ValueError:
            return prop_schema.get('default', 0.0)
    elif prop_type == 'array':
        # Try JSON parse first, fall back to comma-separated
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return [v.strip() for v in value.split(',') if v.strip()]
    else:
        return value


def get_flat_plugin_config(
    env_vars: Optional[Dict[str, str]] = None,
    config_file: Optional[Dict[str, str]] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Get all plugin config values resolved according to hierarchy.

    This is the main function for getting plugin configuration.
    It discovers all plugin schemas and resolves each config key.

    Args:
        env_vars: Environment variables (defaults to os.environ)
        config_file: Config file values (from ArchiveBox.conf)
        overrides: Override values (from User/Crawl/Snapshot config fields)

    Returns:
        Flat dict of all resolved config values.
        e.g., {'SAVE_WGET': True, 'WGET_TIMEOUT': 60, ...}
    """
    if env_vars is None:
        env_vars = dict(os.environ)
    if config_file is None:
        config_file = {}

    plugin_configs = discover_plugin_configs()
    flat_config = {}

    for plugin_name, schema in plugin_configs.items():
        properties = schema.get('properties', {})
        for key, prop_schema in properties.items():
            flat_config[key] = resolve_config_value(
                key, prop_schema, env_vars, config_file, overrides
            )

    return flat_config


def export_plugin_config_to_env(
    config: Dict[str, Any],
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """
    Export plugin config values to environment variable format.

    Converts all values to strings suitable for subprocess environment.
    Arrays are JSON-encoded.

    Args:
        config: Flat config dict from get_flat_plugin_config()
        env: Optional existing env dict to update (creates new if None)

    Returns:
        Environment dict with config values as strings.
    """
    if env is None:
        env = {}

    for key, value in config.items():
        if value is None:
            continue
        elif isinstance(value, bool):
            env[key] = 'true' if value else 'false'
        elif isinstance(value, (list, dict)):
            env[key] = json.dumps(value)
        else:
            env[key] = str(value)

    return env


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

# Default icons for known extractor plugins (emoji or short HTML)
DEFAULT_PLUGIN_ICONS = {
    'screenshot': '📷',
    'pdf': '📄',
    'singlefile': '📦',
    'dom': '🌐',
    'wget': '📥',
    'media': '🎬',
    'git': '📂',
    'readability': '📖',
    'mercury': '☿️',
    'favicon': '⭐',
    'title': '📝',
    'headers': '📋',
    'archive_org': '🏛️',
    'htmltotext': '📃',
    'warc': '🗄️',
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
    Get the icon for a plugin.

    First checks for plugin-provided icon.html template,
    then falls back to DEFAULT_PLUGIN_ICONS.

    Args:
        plugin: Plugin name (e.g., 'screenshot', '15_singlefile')

    Returns:
        Icon HTML/emoji string.
    """
    base_name = get_plugin_name(plugin)

    # Try plugin-provided icon template
    icon_template = get_plugin_template(plugin, 'icon', fallback=False)
    if icon_template:
        return icon_template.strip()

    # Fall back to default icon
    return DEFAULT_PLUGIN_ICONS.get(base_name, '📁')


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

    from machine.models import Binary

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
    from machine.models import Binary, Machine

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
    Dispatches to Model.from_jsonl() for each record type.

    Args:
        records: List of JSONL record dicts from result['records']
        overrides: Dict with 'snapshot', 'crawl', 'dependency', 'created_by_id', etc.

    Returns:
        Dict with counts by record type
    """
    stats = {}
    overrides = overrides or {}

    for record in records:
        record_type = record.get('type')
        if not record_type:
            continue

        # Skip ArchiveResult records (they update the calling ArchiveResult, not create new ones)
        if record_type == 'ArchiveResult':
            continue

        try:
            # Dispatch to appropriate model's from_jsonl() method
            if record_type == 'Snapshot':
                from core.models import Snapshot
                obj = Snapshot.from_jsonl(record.copy(), overrides)
                if obj:
                    stats['Snapshot'] = stats.get('Snapshot', 0) + 1

            elif record_type == 'Tag':
                from core.models import Tag
                obj = Tag.from_jsonl(record.copy(), overrides)
                if obj:
                    stats['Tag'] = stats.get('Tag', 0) + 1

            elif record_type == 'Binary':
                from machine.models import Binary
                obj = Binary.from_jsonl(record.copy(), overrides)
                if obj:
                    stats['Binary'] = stats.get('Binary', 0) + 1

            elif record_type == 'Machine':
                from machine.models import Machine
                obj = Machine.from_jsonl(record.copy(), overrides)
                if obj:
                    stats['Machine'] = stats.get('Machine', 0) + 1

            else:
                import sys
                print(f"Warning: Unknown record type '{record_type}' from hook output", file=sys.stderr)

        except Exception as e:
            import sys
            print(f"Warning: Failed to create {record_type}: {e}", file=sys.stderr)
            continue

    return stats


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
        pid_file: Path to hook.pid file
        sig: Signal to send (default SIGTERM)
        validate: If True, validate process identity before killing (default: True)
    """
    from archivebox.misc.process_utils import safe_kill_process
    
    if validate:
        # Use safe kill with validation
        cmd_file = pid_file.parent / 'cmd.sh'
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


