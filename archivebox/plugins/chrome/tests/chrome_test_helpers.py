"""
Shared Chrome test helpers for plugin integration tests.

This module provides common utilities for Chrome-based plugin tests, reducing
duplication across test files. It uses the JavaScript utilities from chrome_utils.js
where appropriate.

Usage:
    # For simple tests (screenshot, dom, pdf, etc.):
    from archivebox.plugins.chrome.tests.chrome_test_helpers import (
        get_test_env,
        get_lib_dir,
        find_chromium_binary,
    )

    # For extension tests (ublock, istilldontcareaboutcookies, twocaptcha):
    from archivebox.plugins.chrome.tests.chrome_test_helpers import (
        setup_test_env,
        launch_chromium_session,
        kill_chromium_session,
    )

    # For tab-based tests (infiniscroll, modalcloser):
    from archivebox.plugins.chrome.tests.chrome_test_helpers import (
        setup_chrome_session,
        cleanup_chrome,
        chrome_session,
    )
"""

import json
import os
import platform
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional
from contextlib import contextmanager


# Plugin directory locations
CHROME_PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = CHROME_PLUGIN_DIR.parent

# Hook script locations
CHROME_INSTALL_HOOK = CHROME_PLUGIN_DIR / 'on_Crawl__00_install_puppeteer_chromium.py'
CHROME_LAUNCH_HOOK = CHROME_PLUGIN_DIR / 'on_Crawl__30_chrome_launch.bg.js'
CHROME_TAB_HOOK = CHROME_PLUGIN_DIR / 'on_Snapshot__20_chrome_tab.bg.js'
CHROME_NAVIGATE_HOOK = next(CHROME_PLUGIN_DIR.glob('on_Snapshot__*_chrome_navigate.*'), None)
CHROME_UTILS = CHROME_PLUGIN_DIR / 'chrome_utils.js'


def get_lib_dir() -> Path:
    """Get LIB_DIR for tests, checking env first then ArchiveBox config.

    Returns the path to the lib directory, checking:
    1. LIB_DIR environment variable
    2. ArchiveBox config STORAGE_CONFIG.LIB_DIR
    """
    if os.environ.get('LIB_DIR'):
        return Path(os.environ['LIB_DIR'])
    from archivebox.config.common import STORAGE_CONFIG
    return Path(str(STORAGE_CONFIG.LIB_DIR))


def get_node_modules_dir() -> Path:
    """Get NODE_MODULES_DIR for tests, checking env first.

    Returns the path to the node_modules directory, checking:
    1. NODE_MODULES_DIR environment variable
    2. Computed from LIB_DIR
    """
    if os.environ.get('NODE_MODULES_DIR'):
        return Path(os.environ['NODE_MODULES_DIR'])
    lib_dir = get_lib_dir()
    return lib_dir / 'npm' / 'node_modules'


def get_test_env() -> dict:
    """Get environment dict with NODE_MODULES_DIR and LIB_DIR set correctly for tests.

    Returns a copy of os.environ with NODE_MODULES_DIR and LIB_DIR added/updated.
    Use this for all subprocess calls in simple plugin tests (screenshot, dom, pdf).
    """
    env = os.environ.copy()
    lib_dir = get_lib_dir()
    env['LIB_DIR'] = str(lib_dir)
    env['NODE_MODULES_DIR'] = str(get_node_modules_dir())
    return env


def find_chromium_binary(data_dir: Optional[str] = None) -> Optional[str]:
    """Find the Chromium binary using chrome_utils.js findChromium().

    This uses the centralized findChromium() function which checks:
    - CHROME_BINARY env var
    - @puppeteer/browsers install locations
    - System Chromium locations
    - Falls back to Chrome (with warning)

    Args:
        data_dir: Directory where chromium was installed (contains chromium/ subdir)

    Returns:
        Path to Chromium binary or None if not found
    """
    search_dir = data_dir or os.environ.get('DATA_DIR', '.')
    result = subprocess.run(
        ['node', str(CHROME_UTILS), 'findChromium', str(search_dir)],
        capture_output=True,
        text=True,
        timeout=10
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def get_extensions_dir() -> str:
    """Get the Chrome extensions directory using chrome_utils.js getExtensionsDir().

    This uses the centralized path calculation from chrome_utils.js which checks:
    - CHROME_EXTENSIONS_DIR env var
    - DATA_DIR/personas/ACTIVE_PERSONA/chrome_extensions

    Returns:
        Path to extensions directory
    """
    result = subprocess.run(
        ['node', str(CHROME_UTILS), 'getExtensionsDir'],
        capture_output=True,
        text=True,
        timeout=10,
        env=get_test_env()
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    # Fallback to default computation if JS call fails
    data_dir = os.environ.get('DATA_DIR', './data')
    persona = os.environ.get('ACTIVE_PERSONA', 'Default')
    return str(Path(data_dir) / 'personas' / persona / 'chrome_extensions')


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

    Calls chrome install hook which handles puppeteer-core and chromium installation.
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

    # Call chrome install hook (installs puppeteer-core and chromium, outputs JSONL)
    result = subprocess.run(
        ['python', str(CHROME_INSTALL_HOOK)],
        capture_output=True, text=True, timeout=120, env=env
    )
    if result.returncode != 0:
        pytest.skip(f"Chrome install hook failed: {result.stderr}")

    # Parse JSONL output to get CHROME_BINARY
    chrome_binary = None
    for line in result.stdout.strip().split('\n'):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if data.get('type') == 'Binary' and data.get('abspath'):
                chrome_binary = data['abspath']
                break
        except json.JSONDecodeError:
            continue

    if not chrome_binary or not Path(chrome_binary).exists():
        pytest.skip(f"Chromium binary not found: {chrome_binary}")

    env['CHROME_BINARY'] = chrome_binary
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

    Args:
        chrome_launch_process: The Popen object from launch_chromium_session
        chrome_dir: The chrome directory containing chrome.pid
    """
    try:
        chrome_launch_process.send_signal(signal.SIGTERM)
        chrome_launch_process.wait(timeout=5)
    except Exception:
        pass
    chrome_pid_file = chrome_dir / 'chrome.pid'
    if chrome_pid_file.exists():
        try:
            chrome_pid = int(chrome_pid_file.read_text().strip())
            os.kill(chrome_pid, signal.SIGKILL)
        except (OSError, ValueError):
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


def setup_chrome_session(
    tmpdir: Path,
    crawl_id: str = 'test-crawl',
    snapshot_id: str = 'test-snapshot',
    test_url: str = 'about:blank',
    navigate: bool = True,
    timeout: int = 15,
) -> Tuple[subprocess.Popen, int, Path]:
    """Set up a Chrome session with tab and optional navigation.

    Creates the directory structure, launches Chrome, creates a tab,
    and optionally navigates to the test URL.

    Args:
        tmpdir: Temporary directory for test files
        crawl_id: ID to use for the crawl
        snapshot_id: ID to use for the snapshot
        test_url: URL to navigate to (if navigate=True)
        navigate: Whether to navigate to the URL after creating tab
        timeout: Seconds to wait for Chrome to start

    Returns:
        Tuple of (chrome_launch_process, chrome_pid, snapshot_chrome_dir)

    Raises:
        RuntimeError: If Chrome fails to start or tab creation fails
    """
    crawl_dir = Path(tmpdir) / 'crawl'
    crawl_dir.mkdir(exist_ok=True)
    chrome_dir = crawl_dir / 'chrome'
    chrome_dir.mkdir(exist_ok=True)

    env = get_test_env()
    env['CHROME_HEADLESS'] = 'true'

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

    # Navigate to URL if requested
    if navigate and CHROME_NAVIGATE_HOOK and test_url != 'about:blank':
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

    return chrome_launch_process, chrome_pid, snapshot_chrome_dir


def cleanup_chrome(chrome_launch_process: subprocess.Popen, chrome_pid: int) -> None:
    """Clean up Chrome processes.

    Sends SIGTERM to the chrome_launch_process and SIGKILL to the Chrome PID.
    Ignores errors if processes are already dead.

    Args:
        chrome_launch_process: The Popen object for the chrome launch hook
        chrome_pid: The PID of the Chrome process
    """
    try:
        chrome_launch_process.send_signal(signal.SIGTERM)
        chrome_launch_process.wait(timeout=5)
    except Exception:
        pass
    try:
        os.kill(chrome_pid, signal.SIGKILL)
    except OSError:
        pass


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

    Usage:
        with chrome_session(tmpdir, test_url='https://example.com') as (process, pid, chrome_dir):
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
        Tuple of (chrome_launch_process, chrome_pid, snapshot_chrome_dir)
    """
    chrome_launch_process = None
    chrome_pid = None
    try:
        chrome_launch_process, chrome_pid, snapshot_chrome_dir = setup_chrome_session(
            tmpdir=tmpdir,
            crawl_id=crawl_id,
            snapshot_id=snapshot_id,
            test_url=test_url,
            navigate=navigate,
            timeout=timeout,
        )
        yield chrome_launch_process, chrome_pid, snapshot_chrome_dir
    finally:
        if chrome_launch_process and chrome_pid:
            cleanup_chrome(chrome_launch_process, chrome_pid)
