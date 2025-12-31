"""
Chrome test helpers - delegates to chrome_utils.js (single source of truth).

Function names match JS equivalents in snake_case:
    getMachineType -> get_machine_type, getLibDir -> get_lib_dir, etc.
"""

import json
import os
import platform
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any
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


# =============================================================================
# Path Helpers - delegates to chrome_utils.js (single source of truth)
# =============================================================================


def _call_chrome_utils(command: str, *args: str, env: Optional[dict] = None) -> Tuple[int, str, str]:
    """Call chrome_utils.js CLI command. Returns (returncode, stdout, stderr)."""
    cmd = ['node', str(CHROME_UTILS), command] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env or os.environ.copy())
    return result.returncode, result.stdout, result.stderr


def get_machine_type() -> str:
    """Get machine type (e.g., 'x86_64-linux'). Matches JS getMachineType()."""
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
    """Get LIB_DIR path. Matches JS getLibDir()."""
    returncode, stdout, stderr = _call_chrome_utils('getLibDir')
    if returncode != 0:
        raise RuntimeError(f"getLibDir failed: {stderr}")
    return Path(stdout.strip())


def get_node_modules_dir() -> Path:
    """Get NODE_MODULES_DIR path. Matches JS getNodeModulesDir()."""
    returncode, stdout, stderr = _call_chrome_utils('getNodeModulesDir')
    if returncode != 0:
        raise RuntimeError(f"getNodeModulesDir failed: {stderr}")
    return Path(stdout.strip())


def get_extensions_dir() -> str:
    """Get Chrome extensions directory. Matches JS getExtensionsDir()."""
    returncode, stdout, stderr = _call_chrome_utils('getExtensionsDir')
    if returncode != 0:
        raise RuntimeError(f"getExtensionsDir failed: {stderr}")
    return stdout.strip()


def find_chromium(data_dir: Optional[str] = None) -> Optional[str]:
    """Find Chromium binary path. Matches JS findChromium()."""
    env = os.environ.copy()
    if data_dir:
        env['DATA_DIR'] = str(data_dir)
    returncode, stdout, stderr = _call_chrome_utils('findChromium', env=env)
    return stdout.strip() if returncode == 0 and stdout.strip() else None


def kill_chrome(pid: int, output_dir: Optional[str] = None) -> bool:
    """Kill Chrome process by PID. Matches JS killChrome()."""
    args = [str(pid)]
    if output_dir:
        args.append(str(output_dir))
    returncode, stdout, stderr = _call_chrome_utils('killChrome', *args)
    return returncode == 0


def get_test_env() -> dict:
    """Get env dict with all paths set for tests. Matches JS getTestEnv()."""
    env = os.environ.copy()
    returncode, stdout, stderr = _call_chrome_utils('getTestEnv')
    if returncode != 0:
        raise RuntimeError(f"getTestEnv failed: {stderr}")
    env.update(json.loads(stdout))
    return env


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
    """Run a hook script. Returns (returncode, stdout, stderr)."""
    if env is None:
        env = get_test_env()

    if hook_script.suffix == '.py':
        cmd = ['python', str(hook_script)]
    elif hook_script.suffix == '.js':
        cmd = ['node', str(hook_script)]
    else:
        cmd = [str(hook_script)]

    cmd.extend([f'--url={url}', f'--snapshot-id={snapshot_id}'])
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, env=env, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def parse_jsonl_output(stdout: str, record_type: str = 'ArchiveResult') -> Optional[Dict[str, Any]]:
    """Parse JSONL output, return first record matching type."""
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


def run_hook_and_parse(
    hook_script: Path,
    url: str,
    snapshot_id: str,
    cwd: Optional[Path] = None,
    env: Optional[dict] = None,
    timeout: int = 60,
    extra_args: Optional[List[str]] = None,
) -> Tuple[int, Optional[Dict[str, Any]], str]:
    """Run hook and parse JSONL output. Returns (returncode, parsed_result, stderr)."""
    returncode, stdout, stderr = run_hook(hook_script, url, snapshot_id, cwd=cwd, env=env, timeout=timeout, extra_args=extra_args)
    return returncode, parse_jsonl_output(stdout), stderr


# =============================================================================
# Extension Test Helpers (ublock, istilldontcareaboutcookies, twocaptcha)
# =============================================================================


def setup_test_env(tmpdir: Path) -> dict:
    """Set up isolated data/lib directory structure for extension tests.
    Returns env dict with DATA_DIR, LIB_DIR, CHROME_BINARY, etc.
    """
    import pytest

    machine_type = get_machine_type()

    # Create directory structure
    data_dir = tmpdir / 'data'
    lib_dir = data_dir / 'lib' / machine_type
    npm_dir = lib_dir / 'npm'
    npm_bin_dir = npm_dir / '.bin'
    node_modules_dir = npm_dir / 'node_modules'
    chrome_extensions_dir = data_dir / 'personas' / 'Default' / 'chrome_extensions'
    date_str = datetime.now().strftime('%Y%m%d')
    users_dir = data_dir / 'users' / 'testuser'
    crawls_dir = users_dir / 'crawls' / date_str
    snapshots_dir = users_dir / 'snapshots' / date_str

    for d in [node_modules_dir, npm_bin_dir, chrome_extensions_dir, crawls_dir, snapshots_dir]:
        d.mkdir(parents=True, exist_ok=True)

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
    if 'CHROME_HEADLESS' not in os.environ:
        env['CHROME_HEADLESS'] = 'true'

    # Install Chrome
    result = subprocess.run(['python', str(CHROME_INSTALL_HOOK)], capture_output=True, text=True, timeout=120, env=env)
    if result.returncode != 0:
        pytest.skip(f"Chrome install failed: {result.stderr}")

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
    """Launch Chromium and return (process, cdp_url)."""
    chrome_dir.mkdir(parents=True, exist_ok=True)

    chrome_launch_process = subprocess.Popen(
        ['node', str(CHROME_LAUNCH_HOOK), f'--crawl-id={crawl_id}'],
        cwd=str(chrome_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )

    cdp_url = None
    for _ in range(20):
        if chrome_launch_process.poll() is not None:
            stdout, stderr = chrome_launch_process.communicate()
            raise RuntimeError(f"Chromium launch failed:\n{stdout}\n{stderr}")
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
    """Clean up Chromium process."""
    try:
        chrome_launch_process.send_signal(signal.SIGTERM)
        chrome_launch_process.wait(timeout=5)
    except Exception:
        pass

    chrome_pid_file = chrome_dir / 'chrome.pid'
    if chrome_pid_file.exists():
        try:
            chrome_pid = int(chrome_pid_file.read_text().strip())
            kill_chrome(chrome_pid, str(chrome_dir))
        except (ValueError, FileNotFoundError):
            pass


@contextmanager
def chromium_session(env: dict, chrome_dir: Path, crawl_id: str):
    """Context manager for Chromium sessions with automatic cleanup."""
    chrome_launch_process = None
    try:
        chrome_launch_process, cdp_url = launch_chromium_session(env, chrome_dir, crawl_id)
        yield chrome_launch_process, cdp_url
    finally:
        if chrome_launch_process:
            kill_chromium_session(chrome_launch_process, chrome_dir)


# =============================================================================
# Tab-based Test Helpers (infiniscroll, modalcloser)
# =============================================================================


def setup_chrome_session(
    tmpdir: Path,
    crawl_id: str = 'test-crawl',
    snapshot_id: str = 'test-snapshot',
    test_url: str = 'about:blank',
    navigate: bool = True,
    timeout: int = 15,
) -> Tuple[subprocess.Popen, int, Path]:
    """Set up Chrome session with tab. Returns (process, pid, snapshot_chrome_dir)."""
    crawl_dir = Path(tmpdir) / 'crawl'
    crawl_dir.mkdir(exist_ok=True)
    chrome_dir = crawl_dir / 'chrome'
    chrome_dir.mkdir(exist_ok=True)

    env = get_test_env()
    env['CHROME_HEADLESS'] = 'true'

    chrome_launch_process = subprocess.Popen(
        ['node', str(CHROME_LAUNCH_HOOK), f'--crawl-id={crawl_id}'],
        cwd=str(chrome_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )

    for _ in range(timeout):
        if chrome_launch_process.poll() is not None:
            stdout, stderr = chrome_launch_process.communicate()
            raise RuntimeError(f"Chrome launch failed:\n{stdout}\n{stderr}")
        if (chrome_dir / 'cdp_url.txt').exists():
            break
        time.sleep(1)

    if not (chrome_dir / 'cdp_url.txt').exists():
        raise RuntimeError(f"Chrome CDP URL not found after {timeout}s")

    chrome_pid = int((chrome_dir / 'chrome.pid').read_text().strip())

    snapshot_dir = Path(tmpdir) / 'snapshot'
    snapshot_dir.mkdir(exist_ok=True)
    snapshot_chrome_dir = snapshot_dir / 'chrome'
    snapshot_chrome_dir.mkdir(exist_ok=True)

    tab_env = env.copy()
    tab_env['CRAWL_OUTPUT_DIR'] = str(crawl_dir)
    result = subprocess.run(
        ['node', str(CHROME_TAB_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}', f'--crawl-id={crawl_id}'],
        cwd=str(snapshot_chrome_dir), capture_output=True, text=True, timeout=60, env=tab_env
    )
    if result.returncode != 0:
        cleanup_chrome(chrome_launch_process, chrome_pid)
        raise RuntimeError(f"Tab creation failed: {result.stderr}")

    if navigate and CHROME_NAVIGATE_HOOK and test_url != 'about:blank':
        result = subprocess.run(
            ['node', str(CHROME_NAVIGATE_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
            cwd=str(snapshot_chrome_dir), capture_output=True, text=True, timeout=120, env=env
        )
        if result.returncode != 0:
            cleanup_chrome(chrome_launch_process, chrome_pid)
            raise RuntimeError(f"Navigation failed: {result.stderr}")

    return chrome_launch_process, chrome_pid, snapshot_chrome_dir


def cleanup_chrome(chrome_launch_process: subprocess.Popen, chrome_pid: int, chrome_dir: Optional[Path] = None) -> None:
    """Clean up Chrome processes."""
    try:
        chrome_launch_process.send_signal(signal.SIGTERM)
        chrome_launch_process.wait(timeout=5)
    except Exception:
        pass
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
    """Context manager for Chrome sessions with automatic cleanup."""
    chrome_launch_process = None
    chrome_pid = None
    try:
        chrome_launch_process, chrome_pid, snapshot_chrome_dir = setup_chrome_session(
            tmpdir=tmpdir, crawl_id=crawl_id, snapshot_id=snapshot_id, test_url=test_url, navigate=navigate, timeout=timeout
        )
        yield chrome_launch_process, chrome_pid, snapshot_chrome_dir
    finally:
        if chrome_launch_process and chrome_pid:
            cleanup_chrome(chrome_launch_process, chrome_pid)
