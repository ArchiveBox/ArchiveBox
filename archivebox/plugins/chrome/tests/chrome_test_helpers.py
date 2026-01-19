"""
Shared Chrome test helpers for plugin integration tests.

This module provides common utilities for Chrome-based plugin tests, reducing
duplication across test files. Functions delegate to chrome_utils.js (the single
source of truth) with Python fallbacks.

Function names match the JS equivalents in snake_case:
    JS: getMachineType()  -> Python: get_machine_type()
    JS: getLibDir()       -> Python: get_lib_dir()
    JS: getNodeModulesDir() -> Python: get_node_modules_dir()
    JS: getExtensionsDir() -> Python: get_extensions_dir()
    JS: findChromium()    -> Python: find_chromium()
    JS: killChrome()      -> Python: kill_chrome()
    JS: getTestEnv()      -> Python: get_test_env()

Usage:
    # Path helpers (delegate to chrome_utils.js):
    from archivebox.plugins.chrome.tests.chrome_test_helpers import (
        get_test_env,           # env dict with LIB_DIR, NODE_MODULES_DIR, MACHINE_TYPE
        get_machine_type,       # e.g., 'x86_64-linux', 'arm64-darwin'
        get_lib_dir,            # Path to lib dir
        get_node_modules_dir,   # Path to node_modules
        get_extensions_dir,     # Path to chrome extensions
        find_chromium,          # Find Chrome/Chromium binary
        kill_chrome,            # Kill Chrome process by PID
    )

    # Test file helpers:
    from archivebox.plugins.chrome.tests.chrome_test_helpers import (
        get_plugin_dir,         # get_plugin_dir(__file__) -> plugin dir Path
        get_hook_script,        # Find hook script by glob pattern
        PLUGINS_ROOT,           # Path to plugins root
        LIB_DIR,                # Path to lib dir (lazy-loaded)
        NODE_MODULES_DIR,       # Path to node_modules (lazy-loaded)
    )

    # For Chrome session tests:
    from archivebox.plugins.chrome.tests.chrome_test_helpers import (
        chrome_session,         # Context manager (Full Chrome + tab setup with automatic cleanup)
        cleanup_chrome,         # Manual cleanup by PID (rarely needed)
    )

    # For extension tests:
    from archivebox.plugins.chrome.tests.chrome_test_helpers import (
        setup_test_env,         # Full dir structure + Chrome install
        launch_chromium_session, # Launch Chrome, return CDP URL
        kill_chromium_session,   # Cleanup Chrome
    )

    # Run hooks and parse JSONL:
    from archivebox.plugins.chrome.tests.chrome_test_helpers import (
        run_hook,               # Run hook, return (returncode, stdout, stderr)
        parse_jsonl_output,     # Parse JSONL from stdout
    )
"""

import json
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any
from contextlib import contextmanager


# Plugin directory locations
CHROME_PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = CHROME_PLUGIN_DIR.parent

# Hook script locations
CHROME_INSTALL_HOOK = CHROME_PLUGIN_DIR / 'on_Crawl__70_chrome_install.py'
CHROME_LAUNCH_HOOK = CHROME_PLUGIN_DIR / 'on_Crawl__90_chrome_launch.bg.js'
CHROME_TAB_HOOK = CHROME_PLUGIN_DIR / 'on_Snapshot__10_chrome_tab.bg.js'
CHROME_NAVIGATE_HOOK = next(CHROME_PLUGIN_DIR.glob('on_Snapshot__*_chrome_navigate.*'), None)
CHROME_UTILS = CHROME_PLUGIN_DIR / 'chrome_utils.js'
PUPPETEER_BINARY_HOOK = PLUGINS_ROOT / 'puppeteer' / 'on_Binary__12_puppeteer_install.py'
PUPPETEER_CRAWL_HOOK = PLUGINS_ROOT / 'puppeteer' / 'on_Crawl__60_puppeteer_install.py'
NPM_BINARY_HOOK = PLUGINS_ROOT / 'npm' / 'on_Binary__10_npm_install.py'


# =============================================================================
# Path Helpers - delegates to chrome_utils.js with Python fallback
# Function names match JS: getMachineType -> get_machine_type, etc.
# =============================================================================


def _call_chrome_utils(command: str, *args: str, env: Optional[dict] = None) -> Tuple[int, str, str]:
    """Call chrome_utils.js CLI command (internal helper).

    This is the central dispatch for calling the JS utilities from Python.
    All path calculations and Chrome operations are centralized in chrome_utils.js
    to ensure consistency between Python and JavaScript code.

    Args:
        command: The CLI command (e.g., 'findChromium', 'getTestEnv')
        *args: Additional command arguments
        env: Environment dict (default: current env)

    Returns:
        Tuple of (returncode, stdout, stderr)
    """
    cmd = ['node', str(CHROME_UTILS), command] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        env=env or os.environ.copy()
    )
    return result.returncode, result.stdout, result.stderr


def get_plugin_dir(test_file: str) -> Path:
    """Get the plugin directory from a test file path.

    Usage:
        PLUGIN_DIR = get_plugin_dir(__file__)

    Args:
        test_file: The __file__ of the test module (e.g., test_screenshot.py)

    Returns:
        Path to the plugin directory (e.g., plugins/screenshot/)
    """
    return Path(test_file).parent.parent


def get_hook_script(plugin_dir: Path, pattern: str) -> Optional[Path]:
    """Find a hook script in a plugin directory by pattern.

    Usage:
        HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_screenshot.*')

    Args:
        plugin_dir: Path to the plugin directory
        pattern: Glob pattern to match

    Returns:
        Path to the hook script or None if not found
    """
    matches = list(plugin_dir.glob(pattern))
    return matches[0] if matches else None


def get_machine_type() -> str:
    """Get machine type string (e.g., 'x86_64-linux', 'arm64-darwin').

    Matches JS: getMachineType()

    Tries chrome_utils.js first, falls back to Python computation.
    """
    # Try JS first (single source of truth)
    returncode, stdout, stderr = _call_chrome_utils('getMachineType')
    if returncode == 0 and stdout.strip():
        return stdout.strip()

    # Fallback to Python computation
    if os.environ.get('MACHINE_TYPE'):
        return os.environ['MACHINE_TYPE']

    machine = platform.machine().lower()
    system = platform.system().lower()
    if machine in ('arm64', 'aarch64'):
        machine = 'arm64'
    elif machine in ('x86_64', 'amd64'):
        machine = 'x86_64'
    return f"{machine}-{system}"


def get_lib_dir() -> Path:
    """Get LIB_DIR path for platform-specific binaries.

    Matches JS: getLibDir()

    Tries chrome_utils.js first, falls back to Python computation.
    """
    # Try JS first
    returncode, stdout, stderr = _call_chrome_utils('getLibDir')
    if returncode == 0 and stdout.strip():
        return Path(stdout.strip())

    # Fallback to Python
    if os.environ.get('LIB_DIR'):
        return Path(os.environ['LIB_DIR'])
    raise Exception('LIB_DIR env var must be set!')


def get_node_modules_dir() -> Path:
    """Get NODE_MODULES_DIR path for npm packages.

    Matches JS: getNodeModulesDir()

    Tries chrome_utils.js first, falls back to Python computation.
    """
    # Try JS first
    returncode, stdout, stderr = _call_chrome_utils('getNodeModulesDir')
    if returncode == 0 and stdout.strip():
        return Path(stdout.strip())

    # Fallback to Python
    if os.environ.get('NODE_MODULES_DIR'):
        return Path(os.environ['NODE_MODULES_DIR'])
    lib_dir = get_lib_dir()
    return lib_dir / 'npm' / 'node_modules'


def get_extensions_dir() -> str:
    """Get the Chrome extensions directory path.

    Matches JS: getExtensionsDir()

    Tries chrome_utils.js first, falls back to Python computation.
    """
    try:
        returncode, stdout, stderr = _call_chrome_utils('getExtensionsDir')
        if returncode == 0 and stdout.strip():
            return stdout.strip()
    except subprocess.TimeoutExpired:
        pass  # Fall through to default computation

    # Fallback to default computation if JS call fails
    data_dir = os.environ.get('DATA_DIR', '.')
    persona = os.environ.get('ACTIVE_PERSONA', 'Default')
    return str(Path(data_dir) / 'personas' / persona / 'chrome_extensions')


def find_chromium(data_dir: Optional[str] = None) -> Optional[str]:
    """Find the Chromium binary path.

    Matches JS: findChromium()

    Uses chrome_utils.js which checks:
    - CHROME_BINARY env var
    - @puppeteer/browsers install locations
    - System Chromium locations
    - Falls back to Chrome (with warning)

    Args:
        data_dir: Optional DATA_DIR override

    Returns:
        Path to Chromium binary or None if not found
    """
    env = os.environ.copy()
    if data_dir:
        env['DATA_DIR'] = str(data_dir)
    returncode, stdout, stderr = _call_chrome_utils('findChromium', env=env)
    if returncode == 0 and stdout.strip():
        return stdout.strip()
    return None


def kill_chrome(pid: int, output_dir: Optional[str] = None) -> bool:
    """Kill a Chrome process by PID.

    Matches JS: killChrome()

    Uses chrome_utils.js which handles:
    - SIGTERM then SIGKILL
    - Process group killing
    - Zombie process cleanup

    Args:
        pid: Process ID to kill
        output_dir: Optional chrome output directory for PID file cleanup

    Returns:
        True if the kill command succeeded
    """
    args = [str(pid)]
    if output_dir:
        args.append(str(output_dir))
    returncode, stdout, stderr = _call_chrome_utils('killChrome', *args)
    return returncode == 0


def get_test_env() -> dict:
    """Get environment dict with all paths set correctly for tests.

    Matches JS: getTestEnv()

    Tries chrome_utils.js first for path values, builds env dict.
    Use this for all subprocess calls in plugin tests.
    """
    env = os.environ.copy()

    # Try to get all paths from JS (single source of truth)
    returncode, stdout, stderr = _call_chrome_utils('getTestEnv')
    if returncode == 0 and stdout.strip():
        try:
            js_env = json.loads(stdout)
            env.update(js_env)
            return env
        except json.JSONDecodeError:
            pass

    # Fallback to Python computation
    lib_dir = get_lib_dir()
    env['LIB_DIR'] = str(lib_dir)
    env['NODE_MODULES_DIR'] = str(get_node_modules_dir())
    env['MACHINE_TYPE'] = get_machine_type()
    return env


# Backward compatibility aliases (deprecated, use new names)
find_chromium_binary = find_chromium
kill_chrome_via_js = kill_chrome
get_machine_type_from_js = get_machine_type
get_test_env_from_js = get_test_env


# =============================================================================
# Module-level constants (lazy-loaded on first access)
# Import these directly: from chrome_test_helpers import LIB_DIR, NODE_MODULES_DIR
# =============================================================================

# These are computed once when first accessed
_LIB_DIR: Optional[Path] = None
_NODE_MODULES_DIR: Optional[Path] = None


def _get_lib_dir_cached() -> Path:
    global _LIB_DIR
    if _LIB_DIR is None:
        _LIB_DIR = get_lib_dir()
    return _LIB_DIR


def _get_node_modules_dir_cached() -> Path:
    global _NODE_MODULES_DIR
    if _NODE_MODULES_DIR is None:
        _NODE_MODULES_DIR = get_node_modules_dir()
    return _NODE_MODULES_DIR


# Module-level constants that can be imported directly
# Usage: from chrome_test_helpers import LIB_DIR, NODE_MODULES_DIR
class _LazyPath:
    """Lazy path that computes value on first access."""
    def __init__(self, getter):
        self._getter = getter
        self._value = None

    def __fspath__(self):
        if self._value is None:
            self._value = self._getter()
        return str(self._value)

    def __truediv__(self, other):
        if self._value is None:
            self._value = self._getter()
        return self._value / other

    def __str__(self):
        return self.__fspath__()

    def __repr__(self):
        return f"<LazyPath: {self.__fspath__()}>"


LIB_DIR = _LazyPath(_get_lib_dir_cached)
NODE_MODULES_DIR = _LazyPath(_get_node_modules_dir_cached)


# =============================================================================
# Hook Execution Helpers
# =============================================================================


def run_hook(
    hook_script: Path,
    url: str,
    snapshot_id: str,
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    timeout: int = 60,
    extra_args: Optional[List[str]] = None,
) -> Tuple[int, str, str]:
    """Run a hook script and return (returncode, stdout, stderr).

    Usage:
        returncode, stdout, stderr = run_hook(
            HOOK_SCRIPT, 'https://example.com', 'test-snap-123',
            cwd=tmpdir, env=get_test_env()
        )

    Args:
        hook_script: Path to the hook script
        url: URL to process
        snapshot_id: Snapshot ID
        cwd: Working directory (default: current dir)
        env: Environment dict (default: get_test_env())
        timeout: Timeout in seconds
        extra_args: Additional arguments to pass

    Returns:
        Tuple of (returncode, stdout, stderr)
    """
    if env is None:
        env = get_test_env()

    # Determine interpreter based on file extension
    if hook_script.suffix == '.py':
        cmd = [sys.executable, str(hook_script)]
    elif hook_script.suffix == '.js':
        cmd = ['node', str(hook_script)]
    else:
        cmd = [str(hook_script)]

    cmd.extend([f'--url={url}', f'--snapshot-id={snapshot_id}'])
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout
    )
    return result.returncode, result.stdout, result.stderr


def parse_jsonl_output(stdout: str, record_type: str = 'ArchiveResult') -> Optional[Dict[str, Any]]:
    """Parse JSONL output from hook stdout and return the specified record type.

    Usage:
        result = parse_jsonl_output(stdout)
        if result and result['status'] == 'succeeded':
            print("Success!")

    Args:
        stdout: The stdout from a hook execution
        record_type: The 'type' field to look for (default: 'ArchiveResult')

    Returns:
        The parsed JSON dict or None if not found
    """
    for line in stdout.strip().split('\n'):
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            record = json.loads(line)
            if record.get('type') == record_type:
                return record
        except json.JSONDecodeError:
            continue
    return None


def parse_jsonl_records(stdout: str) -> List[Dict[str, Any]]:
    """Parse all JSONL records from stdout."""
    records: List[Dict[str, Any]] = []
    for line in stdout.strip().split('\n'):
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def apply_machine_updates(records: List[Dict[str, Any]], env: dict) -> None:
    """Apply Machine update records to env dict in-place."""
    for record in records:
        if record.get('type') != 'Machine':
            continue
        config = record.get('config')
        if not isinstance(config, dict):
            continue
        env.update(config)


def install_chromium_with_hooks(env: dict, timeout: int = 300) -> str:
    """Install Chromium via chrome crawl hook + puppeteer/npm hooks.

    Returns absolute path to Chromium binary.
    """
    puppeteer_result = subprocess.run(
        [sys.executable, str(PUPPETEER_CRAWL_HOOK)],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if puppeteer_result.returncode != 0:
        raise RuntimeError(f"Puppeteer crawl hook failed: {puppeteer_result.stderr}")

    puppeteer_record = parse_jsonl_output(puppeteer_result.stdout, record_type='Binary') or {}
    if not puppeteer_record or puppeteer_record.get('name') != 'puppeteer':
        raise RuntimeError("Puppeteer Binary record not emitted by crawl hook")

    npm_cmd = [
        sys.executable,
        str(NPM_BINARY_HOOK),
        '--machine-id=test-machine',
        '--binary-id=test-puppeteer',
        '--name=puppeteer',
        f"--binproviders={puppeteer_record.get('binproviders', '*')}",
    ]
    puppeteer_overrides = puppeteer_record.get('overrides')
    if puppeteer_overrides:
        npm_cmd.append(f'--overrides={json.dumps(puppeteer_overrides)}')

    npm_result = subprocess.run(
        npm_cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if npm_result.returncode != 0:
        raise RuntimeError(f"Npm install failed: {npm_result.stderr}")

    apply_machine_updates(parse_jsonl_records(npm_result.stdout), env)

    chrome_result = subprocess.run(
        [sys.executable, str(CHROME_INSTALL_HOOK)],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if chrome_result.returncode != 0:
        raise RuntimeError(f"Chrome install hook failed: {chrome_result.stderr}")

    chrome_record = parse_jsonl_output(chrome_result.stdout, record_type='Binary') or {}
    if not chrome_record or chrome_record.get('name') not in ('chromium', 'chrome'):
        raise RuntimeError("Chrome Binary record not emitted by crawl hook")

    chromium_cmd = [
        sys.executable,
        str(PUPPETEER_BINARY_HOOK),
        '--machine-id=test-machine',
        '--binary-id=test-chromium',
        f"--name={chrome_record.get('name', 'chromium')}",
        f"--binproviders={chrome_record.get('binproviders', '*')}",
    ]
    chrome_overrides = chrome_record.get('overrides')
    if chrome_overrides:
        chromium_cmd.append(f'--overrides={json.dumps(chrome_overrides)}')

    result = subprocess.run(
        chromium_cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Puppeteer chromium install failed: {result.stderr}")

    records = parse_jsonl_records(result.stdout)
    chromium_record = None
    for record in records:
        if record.get('type') == 'Binary' and record.get('name') in ('chromium', 'chrome'):
            chromium_record = record
            break
    if not chromium_record:
        chromium_record = parse_jsonl_output(result.stdout, record_type='Binary')

    chromium_path = chromium_record.get('abspath')
    if not chromium_path or not Path(chromium_path).exists():
        raise RuntimeError(f"Chromium binary not found after install: {chromium_path}")

    env['CHROME_BINARY'] = chromium_path
    apply_machine_updates(records, env)
    return chromium_path


def run_hook_and_parse(
    hook_script: Path,
    url: str,
    snapshot_id: str,
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    timeout: int = 60,
    extra_args: Optional[List[str]] = None,
) -> Tuple[int, Optional[Dict[str, Any]], str]:
    """Run a hook and parse its JSONL output.

    Convenience function combining run_hook() and parse_jsonl_output().

    Returns:
        Tuple of (returncode, parsed_result_or_none, stderr)
    """
    returncode, stdout, stderr = run_hook(
        hook_script, url, snapshot_id,
        cwd=cwd, env=env, timeout=timeout, extra_args=extra_args
    )
    result = parse_jsonl_output(stdout)
    return returncode, result, stderr


# =============================================================================
# Extension Test Helpers
# Used by extension tests (ublock, istilldontcareaboutcookies, twocaptcha)
# =============================================================================


def setup_test_env(tmpdir: Path) -> dict:
    """Set up isolated data/lib directory structure for extension tests.

    Creates structure matching real ArchiveBox data dir:
        <tmpdir>/data/
            lib/
                arm64-darwin/   (or x86_64-linux, etc.)
                    npm/
                        .bin/
                        node_modules/
            personas/
                Default/
                    chrome_extensions/
            users/
                testuser/
                    crawls/
                    snapshots/

    Calls chrome install hook + puppeteer/npm hooks for Chromium installation.
    Returns env dict with DATA_DIR, LIB_DIR, NPM_BIN_DIR, NODE_MODULES_DIR, CHROME_BINARY, etc.

    Args:
        tmpdir: Base temporary directory for the test

    Returns:
        Environment dict with all paths set, or pytest.skip() if Chrome install fails
    """
    import pytest

    # Determine machine type (matches archivebox.config.paths.get_machine_type())
    machine = platform.machine().lower()
    system = platform.system().lower()
    if machine in ('arm64', 'aarch64'):
        machine = 'arm64'
    elif machine in ('x86_64', 'amd64'):
        machine = 'x86_64'
    machine_type = f"{machine}-{system}"

    # Create proper directory structure matching real ArchiveBox layout
    data_dir = tmpdir / 'data'
    lib_dir = data_dir / 'lib' / machine_type
    npm_dir = lib_dir / 'npm'
    npm_bin_dir = npm_dir / '.bin'
    node_modules_dir = npm_dir / 'node_modules'

    # Extensions go under personas/Default/
    chrome_extensions_dir = data_dir / 'personas' / 'Default' / 'chrome_extensions'

    # User data goes under users/{username}/
    date_str = datetime.now().strftime('%Y%m%d')
    users_dir = data_dir / 'users' / 'testuser'
    crawls_dir = users_dir / 'crawls' / date_str
    snapshots_dir = users_dir / 'snapshots' / date_str

    # Create all directories
    node_modules_dir.mkdir(parents=True, exist_ok=True)
    npm_bin_dir.mkdir(parents=True, exist_ok=True)
    chrome_extensions_dir.mkdir(parents=True, exist_ok=True)
    crawls_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    # Build complete env dict
    env = os.environ.copy()
    env.update({
        'DATA_DIR': str(data_dir),
        'LIB_DIR': str(lib_dir),
        'MACHINE_TYPE': machine_type,
        'NPM_BIN_DIR': str(npm_bin_dir),
        'NODE_MODULES_DIR': str(node_modules_dir),
        'CHROME_EXTENSIONS_DIR': str(chrome_extensions_dir),
        'CRAWLS_DIR': str(crawls_dir),
        'SNAPSHOTS_DIR': str(snapshots_dir),
    })

    # Only set headless if not already in environment (allow override for debugging)
    if 'CHROME_HEADLESS' not in os.environ:
        env['CHROME_HEADLESS'] = 'true'

    try:
        install_chromium_with_hooks(env)
    except RuntimeError as e:
        pytest.skip(str(e))
    return env


def launch_chromium_session(env: dict, chrome_dir: Path, crawl_id: str) -> Tuple[subprocess.Popen, str]:
    """Launch Chromium and return (process, cdp_url).

    This launches Chrome using the chrome launch hook and waits for the CDP URL
    to become available. Use this for extension tests that need direct CDP access.

    Args:
        env: Environment dict (from setup_test_env)
        chrome_dir: Directory for Chrome to write its files (cdp_url.txt, chrome.pid, etc.)
        crawl_id: ID for the crawl

    Returns:
        Tuple of (chrome_launch_process, cdp_url)

    Raises:
        RuntimeError: If Chrome fails to launch or CDP URL not available after 20s
    """
    chrome_dir.mkdir(parents=True, exist_ok=True)

    chrome_launch_process = subprocess.Popen(
        ['node', str(CHROME_LAUNCH_HOOK), f'--crawl-id={crawl_id}'],
        cwd=str(chrome_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )

    # Wait for Chromium to launch and CDP URL to be available
    cdp_url = None
    for i in range(20):
        if chrome_launch_process.poll() is not None:
            stdout, stderr = chrome_launch_process.communicate()
            raise RuntimeError(f"Chromium launch failed:\nStdout: {stdout}\nStderr: {stderr}")
        cdp_file = chrome_dir / 'cdp_url.txt'
        if cdp_file.exists():
            cdp_url = cdp_file.read_text().strip()
            break
        time.sleep(1)

    if not cdp_url:
        chrome_launch_process.kill()
        raise RuntimeError("Chromium CDP URL not found after 20s")

    return chrome_launch_process, cdp_url


def kill_chromium_session(chrome_launch_process: subprocess.Popen, chrome_dir: Path) -> None:
    """Clean up Chromium process launched by launch_chromium_session.

    Uses chrome_utils.js killChrome for proper process group handling.

    Args:
        chrome_launch_process: The Popen object from launch_chromium_session
        chrome_dir: The chrome directory containing chrome.pid
    """
    # First try to terminate the launch process gracefully
    try:
        chrome_launch_process.send_signal(signal.SIGTERM)
        chrome_launch_process.wait(timeout=5)
    except Exception:
        pass

    # Read PID and use JS to kill with proper cleanup
    chrome_pid_file = chrome_dir / 'chrome.pid'
    if chrome_pid_file.exists():
        try:
            chrome_pid = int(chrome_pid_file.read_text().strip())
            kill_chrome(chrome_pid, str(chrome_dir))
        except (ValueError, FileNotFoundError):
            pass


@contextmanager
def chromium_session(env: dict, chrome_dir: Path, crawl_id: str):
    """Context manager for Chromium sessions with automatic cleanup.

    Usage:
        with chromium_session(env, chrome_dir, 'test-crawl') as (process, cdp_url):
            # Use cdp_url to connect with puppeteer
            pass
        # Chromium automatically cleaned up

    Args:
        env: Environment dict (from setup_test_env)
        chrome_dir: Directory for Chrome files
        crawl_id: ID for the crawl

    Yields:
        Tuple of (chrome_launch_process, cdp_url)
    """
    chrome_launch_process = None
    try:
        chrome_launch_process, cdp_url = launch_chromium_session(env, chrome_dir, crawl_id)
        yield chrome_launch_process, cdp_url
    finally:
        if chrome_launch_process:
            kill_chromium_session(chrome_launch_process, chrome_dir)


# =============================================================================
# Tab-based Test Helpers
# Used by tab-based tests (infiniscroll, modalcloser)
# =============================================================================


def cleanup_chrome(chrome_launch_process: subprocess.Popen, chrome_pid: int, chrome_dir: Optional[Path] = None) -> None:
    """Clean up Chrome processes using chrome_utils.js killChrome.

    Uses the centralized kill logic from chrome_utils.js which handles:
    - SIGTERM then SIGKILL
    - Process group killing
    - Zombie process cleanup

    Args:
        chrome_launch_process: The Popen object for the chrome launch hook
        chrome_pid: The PID of the Chrome process
        chrome_dir: Optional path to chrome output directory
    """
    # First try to terminate the launch process gracefully
    try:
        chrome_launch_process.send_signal(signal.SIGTERM)
        chrome_launch_process.wait(timeout=5)
    except Exception:
        pass

    # Use JS to kill Chrome with proper process group handling
    kill_chrome(chrome_pid, str(chrome_dir) if chrome_dir else None)


@contextmanager
def chrome_session(
    tmpdir: Path,
    crawl_id: str = 'test-crawl',
    snapshot_id: str = 'test-snapshot',
    test_url: str = 'about:blank',
    navigate: bool = True,
    timeout: int = 15,
):
    """Context manager for Chrome sessions with automatic cleanup.

    Creates the directory structure, launches Chrome, creates a tab,
    and optionally navigates to the test URL. Automatically cleans up
    Chrome on exit.

    Usage:
        with chrome_session(tmpdir, test_url='https://example.com') as (process, pid, chrome_dir, env):
            # Run tests with chrome session
            pass
        # Chrome automatically cleaned up

    Args:
        tmpdir: Temporary directory for test files
        crawl_id: ID to use for the crawl
        snapshot_id: ID to use for the snapshot
        test_url: URL to navigate to (if navigate=True)
        navigate: Whether to navigate to the URL after creating tab
        timeout: Seconds to wait for Chrome to start

    Yields:
        Tuple of (chrome_launch_process, chrome_pid, snapshot_chrome_dir, env)

    Raises:
        RuntimeError: If Chrome fails to start or tab creation fails
    """
    chrome_launch_process = None
    chrome_pid = None
    try:
        # Create proper directory structure in tmpdir
        machine = platform.machine().lower()
        system = platform.system().lower()
        if machine in ('arm64', 'aarch64'):
            machine = 'arm64'
        elif machine in ('x86_64', 'amd64'):
            machine = 'x86_64'
        machine_type = f"{machine}-{system}"

        data_dir = Path(tmpdir) / 'data'
        lib_dir = data_dir / 'lib' / machine_type
        npm_dir = lib_dir / 'npm'
        node_modules_dir = npm_dir / 'node_modules'

        # Create lib structure for puppeteer installation
        node_modules_dir.mkdir(parents=True, exist_ok=True)

        # Create crawl and snapshot directories
        crawl_dir = Path(tmpdir) / 'crawl'
        crawl_dir.mkdir(exist_ok=True)
        chrome_dir = crawl_dir / 'chrome'
        chrome_dir.mkdir(exist_ok=True)

        # Build env with tmpdir-specific paths
        env = os.environ.copy()
        env.update({
            'DATA_DIR': str(data_dir),
            'LIB_DIR': str(lib_dir),
            'MACHINE_TYPE': machine_type,
            'NODE_MODULES_DIR': str(node_modules_dir),
            'NODE_PATH': str(node_modules_dir),
            'NPM_BIN_DIR': str(npm_dir / '.bin'),
            'CHROME_HEADLESS': 'true',
        })

        # Install Chromium via npm + puppeteer hooks using normal Binary flow
        install_chromium_with_hooks(env)

        # Launch Chrome at crawl level
        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), f'--crawl-id={crawl_id}'],
            cwd=str(chrome_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        # Wait for Chrome to launch
        for i in range(timeout):
            if chrome_launch_process.poll() is not None:
                stdout, stderr = chrome_launch_process.communicate()
                raise RuntimeError(f"Chrome launch failed:\nStdout: {stdout}\nStderr: {stderr}")
            if (chrome_dir / 'cdp_url.txt').exists():
                break
            time.sleep(1)

        if not (chrome_dir / 'cdp_url.txt').exists():
            raise RuntimeError(f"Chrome CDP URL not found after {timeout}s")

        chrome_pid = int((chrome_dir / 'chrome.pid').read_text().strip())

        # Create snapshot directory structure
        snapshot_dir = Path(tmpdir) / 'snapshot'
        snapshot_dir.mkdir(exist_ok=True)
        snapshot_chrome_dir = snapshot_dir / 'chrome'
        snapshot_chrome_dir.mkdir(exist_ok=True)

        # Create tab
        tab_env = env.copy()
        tab_env['CRAWL_OUTPUT_DIR'] = str(crawl_dir)
        try:
            result = subprocess.run(
                ['node', str(CHROME_TAB_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}', f'--crawl-id={crawl_id}'],
                cwd=str(snapshot_chrome_dir),
                capture_output=True,
                text=True,
                timeout=60,
                env=tab_env
            )
            if result.returncode != 0:
                cleanup_chrome(chrome_launch_process, chrome_pid)
                raise RuntimeError(f"Tab creation failed: {result.stderr}")
        except subprocess.TimeoutExpired:
            cleanup_chrome(chrome_launch_process, chrome_pid)
            raise RuntimeError("Tab creation timed out after 60s")

        # Navigate to URL if requested
        if navigate and CHROME_NAVIGATE_HOOK and test_url != 'about:blank':
            try:
                result = subprocess.run(
                    ['node', str(CHROME_NAVIGATE_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                    cwd=str(snapshot_chrome_dir),
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=env
                )
                if result.returncode != 0:
                    cleanup_chrome(chrome_launch_process, chrome_pid)
                    raise RuntimeError(f"Navigation failed: {result.stderr}")
            except subprocess.TimeoutExpired:
                cleanup_chrome(chrome_launch_process, chrome_pid)
                raise RuntimeError("Navigation timed out after 120s")

        yield chrome_launch_process, chrome_pid, snapshot_chrome_dir, env
    finally:
        if chrome_launch_process and chrome_pid:
            cleanup_chrome(chrome_launch_process, chrome_pid)
