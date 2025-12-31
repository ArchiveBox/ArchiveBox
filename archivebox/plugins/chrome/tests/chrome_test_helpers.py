"""
Shared Chrome test helpers for plugin integration tests.

This module provides common utilities for Chrome-based plugin tests, reducing
duplication across test files. It uses the JavaScript utilities from chrome_utils.js
where appropriate.

Usage:
    from archivebox.plugins.chrome.tests.chrome_test_helpers import (
        get_test_env,
        setup_chrome_session,
        cleanup_chrome,
        find_chromium_binary,
        get_node_modules_dir,
    )
"""

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Tuple, Optional
from contextlib import contextmanager


# Plugin directory locations
CHROME_PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = CHROME_PLUGIN_DIR.parent

# Hook script locations
CHROME_LAUNCH_HOOK = CHROME_PLUGIN_DIR / 'on_Crawl__30_chrome_launch.bg.js'
CHROME_TAB_HOOK = CHROME_PLUGIN_DIR / 'on_Snapshot__20_chrome_tab.bg.js'
CHROME_NAVIGATE_HOOK = next(CHROME_PLUGIN_DIR.glob('on_Snapshot__*_chrome_navigate.*'), None)
CHROME_UTILS = CHROME_PLUGIN_DIR / 'chrome_utils.js'


def get_node_modules_dir() -> Path:
    """Get NODE_MODULES_DIR for tests, checking env first.

    Returns the path to the node_modules directory, checking:
    1. NODE_MODULES_DIR environment variable
    2. Computed from LIB_DIR via ArchiveBox config
    """
    if os.environ.get('NODE_MODULES_DIR'):
        return Path(os.environ['NODE_MODULES_DIR'])
    # Otherwise compute from LIB_DIR
    from archivebox.config.common import STORAGE_CONFIG
    lib_dir = Path(os.environ.get('LIB_DIR') or str(STORAGE_CONFIG.LIB_DIR))
    return lib_dir / 'npm' / 'node_modules'


def get_test_env() -> dict:
    """Get environment dict with NODE_MODULES_DIR set correctly for tests.

    Returns a copy of os.environ with NODE_MODULES_DIR added/updated.
    Use this for all subprocess calls in plugin tests.
    """
    env = os.environ.copy()
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
