"""
Integration tests for chrome plugin

Tests verify:
1. Chromium install via @puppeteer/browsers
2. Verify deps with abx-pkg
3. Chrome hooks exist
4. Chromium launches at crawl level
5. Tab creation at snapshot level
6. Tab navigation works
7. Tab cleanup on SIGTERM
8. Chromium cleanup on crawl end

NOTE: We use Chromium instead of Chrome because Chrome 137+ removed support for
--load-extension and --disable-extensions-except flags, which are needed for
loading unpacked extensions in headless mode.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import pytest
import tempfile
import shutil
import platform

from archivebox.plugins.chrome.tests.chrome_test_helpers import (
    get_test_env,
    find_chromium_binary,
    install_chromium_with_hooks,
    CHROME_PLUGIN_DIR as PLUGIN_DIR,
    CHROME_LAUNCH_HOOK,
    CHROME_TAB_HOOK,
    CHROME_NAVIGATE_HOOK,
)

def _get_cookies_via_cdp(port: int, env: dict) -> list[dict]:
    node_script = r"""
const http = require('http');
const WebSocket = require('ws');
const port = process.env.CDP_PORT;

function getTargets() {
  return new Promise((resolve, reject) => {
    const req = http.get(`http://127.0.0.1:${port}/json/list`, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(e);
        }
      });
    });
    req.on('error', reject);
  });
}

(async () => {
  const targets = await getTargets();
  const pageTarget = targets.find(t => t.type === 'page') || targets[0];
  if (!pageTarget) {
    console.error('No page target found');
    process.exit(2);
  }

  const ws = new WebSocket(pageTarget.webSocketDebuggerUrl);
  const timer = setTimeout(() => {
    console.error('Timeout waiting for cookies');
    process.exit(3);
  }, 10000);

  ws.on('open', () => {
    ws.send(JSON.stringify({ id: 1, method: 'Network.getAllCookies' }));
  });

  ws.on('message', (data) => {
    const msg = JSON.parse(data);
    if (msg.id === 1) {
      clearTimeout(timer);
      ws.close();
      if (!msg.result || !msg.result.cookies) {
        console.error('No cookies in response');
        process.exit(4);
      }
      process.stdout.write(JSON.stringify(msg.result.cookies));
      process.exit(0);
    }
  });

  ws.on('error', (err) => {
    console.error(String(err));
    process.exit(5);
  });
})().catch((err) => {
  console.error(String(err));
  process.exit(1);
});
"""

    result = subprocess.run(
        ['node', '-e', node_script],
        capture_output=True,
        text=True,
        timeout=30,
        env=env | {'CDP_PORT': str(port)},
    )
    assert result.returncode == 0, f"Failed to read cookies via CDP: {result.stderr}\nStdout: {result.stdout}"
    return json.loads(result.stdout or '[]')


@pytest.fixture(scope="session", autouse=True)
def ensure_chromium_and_puppeteer_installed(tmp_path_factory):
    """Ensure Chromium and puppeteer are installed before running tests."""
    if not os.environ.get('DATA_DIR'):
        test_data_dir = tmp_path_factory.mktemp('chrome_test_data')
        os.environ['DATA_DIR'] = str(test_data_dir)
    env = get_test_env()

    try:
        chromium_binary = install_chromium_with_hooks(env)
    except RuntimeError as e:
        pytest.skip(str(e))

    if not chromium_binary:
        pytest.skip("Chromium not found after install")

    os.environ['CHROME_BINARY'] = chromium_binary
    for key in ('NODE_MODULES_DIR', 'NODE_PATH', 'PATH'):
        if env.get(key):
            os.environ[key] = env[key]


def test_hook_scripts_exist():
    """Verify chrome hooks exist."""
    assert CHROME_LAUNCH_HOOK.exists(), f"Hook not found: {CHROME_LAUNCH_HOOK}"
    assert CHROME_TAB_HOOK.exists(), f"Hook not found: {CHROME_TAB_HOOK}"
    assert CHROME_NAVIGATE_HOOK.exists(), f"Hook not found: {CHROME_NAVIGATE_HOOK}"


def test_verify_chromium_available():
    """Verify Chromium is available via CHROME_BINARY env var."""
    chromium_binary = os.environ.get('CHROME_BINARY') or find_chromium_binary()

    assert chromium_binary, "Chromium binary should be available (set by fixture or found)"
    assert Path(chromium_binary).exists(), f"Chromium binary should exist at {chromium_binary}"

    # Verify it's actually Chromium by checking version
    result = subprocess.run(
        [chromium_binary, '--version'],
        capture_output=True,
        text=True,
        timeout=10
    )
    assert result.returncode == 0, f"Failed to get Chromium version: {result.stderr}"
    assert 'Chromium' in result.stdout or 'Chrome' in result.stdout, f"Unexpected version output: {result.stdout}"


def test_chrome_launch_and_tab_creation():
    """Integration test: Launch Chrome at crawl level and create tab at snapshot level."""
    with tempfile.TemporaryDirectory() as tmpdir:
        crawl_dir = Path(tmpdir) / 'crawl'
        crawl_dir.mkdir()
        chrome_dir = crawl_dir / 'chrome'
        chrome_dir.mkdir()

        # Get test environment with NODE_MODULES_DIR set
        env = get_test_env()
        env['CHROME_HEADLESS'] = 'true'

        # Launch Chrome at crawl level (background process)
        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), '--crawl-id=test-crawl-123'],
            cwd=str(chrome_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        # Wait for Chrome to launch (check process isn't dead and files exist)
        for i in range(15):  # Wait up to 15 seconds for Chrome to start
            if chrome_launch_process.poll() is not None:
                stdout, stderr = chrome_launch_process.communicate()
                pytest.fail(f"Chrome launch process exited early:\nStdout: {stdout}\nStderr: {stderr}")
            if (chrome_dir / 'cdp_url.txt').exists():
                break
            time.sleep(1)

        # Verify Chrome launch outputs - if it failed, get the error from the process
        if not (chrome_dir / 'cdp_url.txt').exists():
            # Try to get output from the process
            try:
                stdout, stderr = chrome_launch_process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                # Process still running, try to read available output
                stdout = stderr = "(process still running)"

            # Check what files exist
            if chrome_dir.exists():
                files = list(chrome_dir.iterdir())
                # Check if Chrome process is still alive
                if (chrome_dir / 'chrome.pid').exists():
                    chrome_pid = int((chrome_dir / 'chrome.pid').read_text().strip())
                    try:
                        os.kill(chrome_pid, 0)
                        chrome_alive = "yes"
                    except OSError:
                        chrome_alive = "no"
                    pytest.fail(f"cdp_url.txt missing after 15s. Chrome dir files: {files}. Chrome process {chrome_pid} alive: {chrome_alive}\nLaunch stdout: {stdout}\nLaunch stderr: {stderr}")
                else:
                    pytest.fail(f"cdp_url.txt missing. Chrome dir exists with files: {files}\nLaunch stdout: {stdout}\nLaunch stderr: {stderr}")
            else:
                pytest.fail(f"Chrome dir {chrome_dir} doesn't exist\nLaunch stdout: {stdout}\nLaunch stderr: {stderr}")

        assert (chrome_dir / 'cdp_url.txt').exists(), "cdp_url.txt should exist"
        assert (chrome_dir / 'chrome.pid').exists(), "chrome.pid should exist"
        assert (chrome_dir / 'port.txt').exists(), "port.txt should exist"

        cdp_url = (chrome_dir / 'cdp_url.txt').read_text().strip()
        chrome_pid = int((chrome_dir / 'chrome.pid').read_text().strip())

        assert cdp_url.startswith('ws://'), f"CDP URL should be WebSocket URL: {cdp_url}"
        assert chrome_pid > 0, "Chrome PID should be valid"

        # Verify Chrome process is running
        try:
            os.kill(chrome_pid, 0)
        except OSError:
            pytest.fail(f"Chrome process {chrome_pid} is not running")

        # Create snapshot directory and tab
        snapshot_dir = Path(tmpdir) / 'snapshot1'
        snapshot_dir.mkdir()
        snapshot_chrome_dir = snapshot_dir / 'chrome'
        snapshot_chrome_dir.mkdir()

        # Launch tab at snapshot level
        env['CRAWL_OUTPUT_DIR'] = str(crawl_dir)
        result = subprocess.run(
            ['node', str(CHROME_TAB_HOOK), '--url=https://example.com', '--snapshot-id=snap-123', '--crawl-id=test-crawl-123'],
            cwd=str(snapshot_chrome_dir),
            capture_output=True,
            text=True,
            timeout=60,
            env=env
        )

        assert result.returncode == 0, f"Tab creation failed: {result.stderr}\nStdout: {result.stdout}"

        # Verify tab creation outputs
        assert (snapshot_chrome_dir / 'cdp_url.txt').exists(), "Snapshot cdp_url.txt should exist"
        assert (snapshot_chrome_dir / 'target_id.txt').exists(), "target_id.txt should exist"
        assert (snapshot_chrome_dir / 'url.txt').exists(), "url.txt should exist"

        target_id = (snapshot_chrome_dir / 'target_id.txt').read_text().strip()
        assert len(target_id) > 0, "Target ID should not be empty"

        # Cleanup: Kill Chrome and launch process
        try:
            chrome_launch_process.send_signal(signal.SIGTERM)
            chrome_launch_process.wait(timeout=5)
        except:
            pass
        try:
            os.kill(chrome_pid, signal.SIGKILL)
        except OSError:
            pass


def test_cookies_imported_on_launch():
    """Integration test: COOKIES_TXT_FILE is imported at crawl start."""
    with tempfile.TemporaryDirectory() as tmpdir:
        crawl_dir = Path(tmpdir) / 'crawl'
        crawl_dir.mkdir()
        chrome_dir = crawl_dir / 'chrome'
        chrome_dir.mkdir()

        cookies_file = Path(tmpdir) / 'cookies.txt'
        cookies_file.write_text(
            '\n'.join([
                '# Netscape HTTP Cookie File',
                '# https://curl.se/docs/http-cookies.html',
                '# This file was generated by a test',
                '',
                'example.com\tTRUE\t/\tFALSE\t2147483647\tabx_test_cookie\thello',
                '',
            ])
        )

        profile_dir = Path(tmpdir) / 'profile'
        env = get_test_env()
        env.update({
            'CHROME_HEADLESS': 'true',
            'CHROME_USER_DATA_DIR': str(profile_dir),
            'COOKIES_TXT_FILE': str(cookies_file),
        })

        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), '--crawl-id=test-crawl-cookies'],
            cwd=str(chrome_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        for _ in range(15):
            if (chrome_dir / 'port.txt').exists():
                break
            time.sleep(1)

        assert (chrome_dir / 'port.txt').exists(), "port.txt should exist"
        chrome_pid = int((chrome_dir / 'chrome.pid').read_text().strip())
        port = int((chrome_dir / 'port.txt').read_text().strip())

        cookie_found = False
        for _ in range(15):
            cookies = _get_cookies_via_cdp(port, env)
            cookie_found = any(
                c.get('name') == 'abx_test_cookie' and c.get('value') == 'hello'
                for c in cookies
            )
            if cookie_found:
                break
            time.sleep(1)

        assert cookie_found, "Imported cookie should be present in Chrome session"

        # Cleanup
        try:
            chrome_launch_process.send_signal(signal.SIGTERM)
            chrome_launch_process.wait(timeout=5)
        except:
            pass
        try:
            os.kill(chrome_pid, signal.SIGKILL)
        except OSError:
            pass


def test_chrome_navigation():
    """Integration test: Navigate to a URL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        crawl_dir = Path(tmpdir) / 'crawl'
        crawl_dir.mkdir()
        chrome_dir = crawl_dir / 'chrome'
        chrome_dir.mkdir()

        # Launch Chrome (background process)
        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), '--crawl-id=test-crawl-nav'],
            cwd=str(chrome_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=get_test_env() | {'CHROME_HEADLESS': 'true'}
        )

        # Wait for Chrome to launch
        time.sleep(3)

        chrome_pid = int((chrome_dir / 'chrome.pid').read_text().strip())

        # Create snapshot and tab
        snapshot_dir = Path(tmpdir) / 'snapshot1'
        snapshot_dir.mkdir()
        snapshot_chrome_dir = snapshot_dir / 'chrome'
        snapshot_chrome_dir.mkdir()

        result = subprocess.run(
            ['node', str(CHROME_TAB_HOOK), '--url=https://example.com', '--snapshot-id=snap-nav-123', '--crawl-id=test-crawl-nav'],
            cwd=str(snapshot_chrome_dir),
            capture_output=True,
            text=True,
            timeout=60,
            env=get_test_env() | {'CRAWL_OUTPUT_DIR': str(crawl_dir), 'CHROME_HEADLESS': 'true'}
        )
        assert result.returncode == 0, f"Tab creation failed: {result.stderr}"

        # Navigate to URL
        result = subprocess.run(
            ['node', str(CHROME_NAVIGATE_HOOK), '--url=https://example.com', '--snapshot-id=snap-nav-123'],
            cwd=str(snapshot_chrome_dir),
            capture_output=True,
            text=True,
            timeout=120,
            env=get_test_env() | {'CHROME_PAGELOAD_TIMEOUT': '30', 'CHROME_WAIT_FOR': 'load'}
        )

        assert result.returncode == 0, f"Navigation failed: {result.stderr}\nStdout: {result.stdout}"

        # Verify navigation outputs
        assert (snapshot_chrome_dir / 'navigation.json').exists(), "navigation.json should exist"
        assert (snapshot_chrome_dir / 'page_loaded.txt').exists(), "page_loaded.txt should exist"

        nav_data = json.loads((snapshot_chrome_dir / 'navigation.json').read_text())
        assert nav_data.get('status') in [200, 301, 302], f"Should get valid HTTP status: {nav_data}"
        assert nav_data.get('finalUrl'), "Should have final URL"

        # Cleanup
        try:
            chrome_launch_process.send_signal(signal.SIGTERM)
            chrome_launch_process.wait(timeout=5)
        except:
            pass
        try:
            os.kill(chrome_pid, signal.SIGKILL)
        except OSError:
            pass


def test_tab_cleanup_on_sigterm():
    """Integration test: Tab cleanup when receiving SIGTERM."""
    with tempfile.TemporaryDirectory() as tmpdir:
        crawl_dir = Path(tmpdir) / 'crawl'
        crawl_dir.mkdir()
        chrome_dir = crawl_dir / 'chrome'
        chrome_dir.mkdir()

        # Launch Chrome (background process)
        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), '--crawl-id=test-cleanup'],
            cwd=str(chrome_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=get_test_env() | {'CHROME_HEADLESS': 'true'}
        )

        # Wait for Chrome to launch
        time.sleep(3)

        chrome_pid = int((chrome_dir / 'chrome.pid').read_text().strip())

        # Create snapshot and tab - run in background
        snapshot_dir = Path(tmpdir) / 'snapshot1'
        snapshot_dir.mkdir()
        snapshot_chrome_dir = snapshot_dir / 'chrome'
        snapshot_chrome_dir.mkdir()

        tab_process = subprocess.Popen(
            ['node', str(CHROME_TAB_HOOK), '--url=https://example.com', '--snapshot-id=snap-cleanup', '--crawl-id=test-cleanup'],
            cwd=str(snapshot_chrome_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=get_test_env() | {'CRAWL_OUTPUT_DIR': str(crawl_dir), 'CHROME_HEADLESS': 'true'}
        )

        # Wait for tab to be created
        time.sleep(3)

        # Send SIGTERM to tab process
        tab_process.send_signal(signal.SIGTERM)
        stdout, stderr = tab_process.communicate(timeout=10)

        assert tab_process.returncode == 0, f"Tab process should exit cleanly: {stderr}"

        # Chrome should still be running
        try:
            os.kill(chrome_pid, 0)
        except OSError:
            pytest.fail("Chrome should still be running after tab cleanup")

        # Cleanup
        try:
            chrome_launch_process.send_signal(signal.SIGTERM)
            chrome_launch_process.wait(timeout=5)
        except:
            pass
        try:
            os.kill(chrome_pid, signal.SIGKILL)
        except OSError:
            pass


def test_multiple_snapshots_share_chrome():
    """Integration test: Multiple snapshots share one Chrome instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        crawl_dir = Path(tmpdir) / 'crawl'
        crawl_dir.mkdir()
        chrome_dir = crawl_dir / 'chrome'
        chrome_dir.mkdir()

        # Launch Chrome at crawl level
        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), '--crawl-id=test-multi-crawl'],
            cwd=str(chrome_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=get_test_env() | {'CHROME_HEADLESS': 'true'}
        )

        # Wait for Chrome to launch
        for i in range(15):
            if (chrome_dir / 'cdp_url.txt').exists():
                break
            time.sleep(1)

        chrome_pid = int((chrome_dir / 'chrome.pid').read_text().strip())
        crawl_cdp_url = (chrome_dir / 'cdp_url.txt').read_text().strip()

        # Create multiple snapshots that share this Chrome
        snapshot_dirs = []
        target_ids = []

        for snap_num in range(3):
            snapshot_dir = Path(tmpdir) / f'snapshot{snap_num}'
            snapshot_dir.mkdir()
            snapshot_chrome_dir = snapshot_dir / 'chrome'
            snapshot_chrome_dir.mkdir()
            snapshot_dirs.append(snapshot_chrome_dir)

            # Create tab for this snapshot
            result = subprocess.run(
                ['node', str(CHROME_TAB_HOOK), f'--url=https://example.com/{snap_num}', f'--snapshot-id=snap-{snap_num}', '--crawl-id=test-multi-crawl'],
                cwd=str(snapshot_chrome_dir),
                capture_output=True,
                text=True,
                timeout=60,
                env=get_test_env() | {'CRAWL_OUTPUT_DIR': str(crawl_dir), 'CHROME_HEADLESS': 'true'}
            )

            assert result.returncode == 0, f"Tab {snap_num} creation failed: {result.stderr}"

            # Verify each snapshot has its own target_id but same Chrome PID
            assert (snapshot_chrome_dir / 'target_id.txt').exists()
            assert (snapshot_chrome_dir / 'cdp_url.txt').exists()
            assert (snapshot_chrome_dir / 'chrome.pid').exists()

            target_id = (snapshot_chrome_dir / 'target_id.txt').read_text().strip()
            snapshot_cdp_url = (snapshot_chrome_dir / 'cdp_url.txt').read_text().strip()
            snapshot_pid = int((snapshot_chrome_dir / 'chrome.pid').read_text().strip())

            target_ids.append(target_id)

            # All snapshots should share same Chrome
            assert snapshot_pid == chrome_pid, f"Snapshot {snap_num} should use crawl Chrome PID"
            assert snapshot_cdp_url == crawl_cdp_url, f"Snapshot {snap_num} should use crawl CDP URL"

        # All target IDs should be unique (different tabs)
        assert len(set(target_ids)) == 3, f"All snapshots should have unique tabs: {target_ids}"

        # Chrome should still be running with all 3 tabs
        try:
            os.kill(chrome_pid, 0)
        except OSError:
            pytest.fail("Chrome should still be running after creating 3 tabs")

        # Cleanup
        try:
            chrome_launch_process.send_signal(signal.SIGTERM)
            chrome_launch_process.wait(timeout=5)
        except:
            pass
        try:
            os.kill(chrome_pid, signal.SIGKILL)
        except OSError:
            pass


def test_chrome_cleanup_on_crawl_end():
    """Integration test: Chrome cleanup at end of crawl."""
    with tempfile.TemporaryDirectory() as tmpdir:
        crawl_dir = Path(tmpdir) / 'crawl'
        crawl_dir.mkdir()
        chrome_dir = crawl_dir / 'chrome'
        chrome_dir.mkdir()

        # Launch Chrome in background
        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), '--crawl-id=test-crawl-end'],
            cwd=str(chrome_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=get_test_env() | {'CHROME_HEADLESS': 'true'}
        )

        # Wait for Chrome to launch
        time.sleep(3)

        # Verify Chrome is running
        assert (chrome_dir / 'chrome.pid').exists(), "Chrome PID file should exist"
        chrome_pid = int((chrome_dir / 'chrome.pid').read_text().strip())

        try:
            os.kill(chrome_pid, 0)
        except OSError:
            pytest.fail("Chrome should be running")

        # Send SIGTERM to chrome launch process
        chrome_launch_process.send_signal(signal.SIGTERM)
        stdout, stderr = chrome_launch_process.communicate(timeout=10)

        # Wait for cleanup
        time.sleep(3)

        # Verify Chrome process is killed
        try:
            os.kill(chrome_pid, 0)
            pytest.fail("Chrome should be killed after SIGTERM")
        except OSError:
            # Expected - Chrome should be dead
            pass


def test_zombie_prevention_hook_killed():
    """Integration test: Chrome is killed even if hook process is SIGKILL'd."""
    with tempfile.TemporaryDirectory() as tmpdir:
        crawl_dir = Path(tmpdir) / 'crawl'
        crawl_dir.mkdir()
        chrome_dir = crawl_dir / 'chrome'
        chrome_dir.mkdir()

        # Launch Chrome
        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), '--crawl-id=test-zombie'],
            cwd=str(chrome_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=get_test_env() | {'CHROME_HEADLESS': 'true'}
        )

        # Wait for Chrome to launch
        for i in range(15):
            if (chrome_dir / 'chrome.pid').exists():
                break
            time.sleep(1)

        assert (chrome_dir / 'chrome.pid').exists(), "Chrome PID file should exist"

        chrome_pid = int((chrome_dir / 'chrome.pid').read_text().strip())
        hook_pid = chrome_launch_process.pid  # Use the Popen process PID instead of hook.pid file

        # Verify both Chrome and hook are running
        try:
            os.kill(chrome_pid, 0)
            os.kill(hook_pid, 0)
        except OSError:
            pytest.fail("Both Chrome and hook should be running")

        # Simulate hook getting SIGKILL'd (can't cleanup)
        os.kill(hook_pid, signal.SIGKILL)
        time.sleep(1)

        # Chrome should still be running (orphaned)
        try:
            os.kill(chrome_pid, 0)
        except OSError:
            pytest.fail("Chrome should still be running after hook SIGKILL")

        # Simulate Crawl.cleanup() using the actual cleanup logic
        def is_process_alive(pid):
            """Check if a process exists."""
            try:
                os.kill(pid, 0)
                return True
            except (OSError, ProcessLookupError):
                return False

        for pid_file in chrome_dir.glob('**/*.pid'):
            try:
                pid = int(pid_file.read_text().strip())

                # Step 1: SIGTERM for graceful shutdown
                try:
                    try:
                        os.killpg(pid, signal.SIGTERM)
                    except (OSError, ProcessLookupError):
                        os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pid_file.unlink(missing_ok=True)
                    continue

                # Step 2: Wait for graceful shutdown
                time.sleep(2)

                # Step 3: Check if still alive
                if not is_process_alive(pid):
                    pid_file.unlink(missing_ok=True)
                    continue

                # Step 4: Force kill ENTIRE process group with SIGKILL
                try:
                    try:
                        # Always kill entire process group with SIGKILL
                        os.killpg(pid, signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pid_file.unlink(missing_ok=True)
                    continue

                # Step 5: Wait and verify death
                time.sleep(1)

                if not is_process_alive(pid):
                    pid_file.unlink(missing_ok=True)

            except (ValueError, OSError):
                pass

        # Chrome should now be dead
        try:
            os.kill(chrome_pid, 0)
            pytest.fail("Chrome should be killed after cleanup")
        except OSError:
            # Expected - Chrome is dead
            pass


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
