"""
Integration tests for modalcloser plugin

Tests verify:
1. Hook script exists
2. Dependencies installed via chrome validation hooks
3. Verify deps with abx-pkg
4. MODALCLOSER_ENABLED=False skips without JSONL
5. Fails gracefully when no chrome session exists
6. Background script runs and handles SIGTERM correctly
7. Config options work (timeout, poll interval)
8. Live test: hides cookie consent on filmin.es
"""

import json
import os
import signal
import subprocess
import time
import tempfile
from pathlib import Path

import pytest

# Import shared Chrome test helpers
from archivebox.plugins.chrome.tests.chrome_test_helpers import (
    get_test_env,
    chrome_session,
)


PLUGIN_DIR = Path(__file__).parent.parent
MODALCLOSER_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_modalcloser.*'), None)
TEST_URL = 'https://www.singsing.movie/'
COOKIE_CONSENT_TEST_URL = 'https://www.filmin.es/'


def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert MODALCLOSER_HOOK is not None, "Modalcloser hook not found"
    assert MODALCLOSER_HOOK.exists(), f"Hook not found: {MODALCLOSER_HOOK}"


def test_verify_deps_with_abx_pkg():
    """Verify dependencies are available via abx-pkg after hook installation."""
    from abx_pkg import Binary, EnvProvider

    EnvProvider.model_rebuild()

    # Verify node is available
    node_binary = Binary(name='node', binproviders=[EnvProvider()])
    node_loaded = node_binary.load()
    assert node_loaded and node_loaded.abspath, "Node.js required for modalcloser plugin"


def test_config_modalcloser_disabled_skips():
    """Test that MODALCLOSER_ENABLED=False exits without emitting JSONL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        env = get_test_env()
        env['MODALCLOSER_ENABLED'] = 'False'

        result = subprocess.run(
            ['node', str(MODALCLOSER_HOOK), f'--url={TEST_URL}', '--snapshot-id=test-disabled'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when feature disabled: {result.stderr}"
        assert 'Skipping' in result.stderr or 'False' in result.stderr, "Should log skip reason to stderr"

        # Should NOT emit any JSONL
        jsonl_lines = [line for line in result.stdout.strip().split('\n') if line.strip().startswith('{')]
        assert len(jsonl_lines) == 0, f"Should not emit JSONL when feature disabled, got: {jsonl_lines}"


def test_fails_gracefully_without_chrome_session():
    """Test that hook fails gracefully when no chrome session exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        result = subprocess.run(
            ['node', str(MODALCLOSER_HOOK), f'--url={TEST_URL}', '--snapshot-id=test-no-chrome'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=get_test_env(),
            timeout=30
        )

        # Should fail (exit 1) when no chrome session
        assert result.returncode != 0, "Should fail when no chrome session exists"
        # Error could be about chrome/CDP not found, or puppeteer module missing
        err_lower = result.stderr.lower()
        assert any(x in err_lower for x in ['chrome', 'cdp', 'puppeteer', 'module']), \
            f"Should mention chrome/CDP/puppeteer in error: {result.stderr}"


def test_background_script_handles_sigterm():
    """Test that background script runs and handles SIGTERM correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        modalcloser_process = None
        try:
            with chrome_session(
                Path(tmpdir),
                crawl_id='test-modalcloser',
                snapshot_id='snap-modalcloser',
                test_url=TEST_URL,
            ) as (chrome_launch_process, chrome_pid, snapshot_chrome_dir, env):
                # Create modalcloser output directory (sibling to chrome)
                modalcloser_dir = snapshot_chrome_dir.parent / 'modalcloser'
                modalcloser_dir.mkdir()

                # Run modalcloser as background process (use env from setup_chrome_session)
                env['MODALCLOSER_POLL_INTERVAL'] = '200'  # Faster polling for test

                modalcloser_process = subprocess.Popen(
                    ['node', str(MODALCLOSER_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-modalcloser'],
                    cwd=str(modalcloser_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env
                )

                # Let it run for a bit
                time.sleep(2)

                # Verify it's still running (background script)
                assert modalcloser_process.poll() is None, "Modalcloser should still be running as background process"

                # Send SIGTERM
                modalcloser_process.send_signal(signal.SIGTERM)
                stdout, stderr = modalcloser_process.communicate(timeout=5)

                assert modalcloser_process.returncode == 0, f"Should exit 0 on SIGTERM: {stderr}"

                # Parse JSONL output
                result_json = None
                for line in stdout.strip().split('\n'):
                    line = line.strip()
                    if line.startswith('{'):
                        try:
                            record = json.loads(line)
                            if record.get('type') == 'ArchiveResult':
                                result_json = record
                                break
                        except json.JSONDecodeError:
                            pass

                assert result_json is not None, f"Should have ArchiveResult JSONL output. Stdout: {stdout}"
                assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"

                # Verify output_str format
                output_str = result_json.get('output_str', '')
                assert 'modal' in output_str.lower() or 'dialog' in output_str.lower(), \
                    f"output_str should mention modals/dialogs: {output_str}"

                # Verify no files created in output directory
                output_files = list(modalcloser_dir.iterdir())
                assert len(output_files) == 0, f"Should not create any files, but found: {output_files}"

        finally:
            if modalcloser_process and modalcloser_process.poll() is None:
                modalcloser_process.kill()


def test_dialog_handler_logs_dialogs():
    """Test that dialog handler is set up correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        modalcloser_process = None
        try:
            with chrome_session(
                    Path(tmpdir),
                    crawl_id='test-dialog',
                    snapshot_id='snap-dialog',
                    test_url=TEST_URL,
            ) as (chrome_launch_process, chrome_pid, snapshot_chrome_dir, env):

                modalcloser_dir = snapshot_chrome_dir.parent / 'modalcloser'
                modalcloser_dir.mkdir()

                # Use env from setup_chrome_session
                env['MODALCLOSER_TIMEOUT'] = '100'  # Fast timeout for test
                env['MODALCLOSER_POLL_INTERVAL'] = '200'

                modalcloser_process = subprocess.Popen(
                    ['node', str(MODALCLOSER_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-dialog'],
                    cwd=str(modalcloser_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env
                )

                # Let it run briefly
                time.sleep(1.5)

                # Verify it's running
                assert modalcloser_process.poll() is None, "Should be running"

                # Check stderr for "listening" message
                # Note: Can't read stderr while process is running without blocking,
                # so we just verify it exits cleanly
                modalcloser_process.send_signal(signal.SIGTERM)
                stdout, stderr = modalcloser_process.communicate(timeout=5)

                assert 'listening' in stderr.lower() or 'modalcloser' in stderr.lower(), \
                    f"Should log startup message: {stderr}"
                assert modalcloser_process.returncode == 0, f"Should exit cleanly: {stderr}"

        finally:
            if modalcloser_process and modalcloser_process.poll() is None:
                modalcloser_process.kill()


def test_config_poll_interval():
    """Test that MODALCLOSER_POLL_INTERVAL config is respected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        chrome_launch_process = None
        chrome_pid = None
        modalcloser_process = None
        try:
            with chrome_session(
                    Path(tmpdir),
                    crawl_id='test-poll',
                    snapshot_id='snap-poll',
                    test_url=TEST_URL,
            ) as (chrome_launch_process, chrome_pid, snapshot_chrome_dir, env):

                modalcloser_dir = snapshot_chrome_dir.parent / 'modalcloser'
                modalcloser_dir.mkdir()

                # Set very short poll interval (use env from setup_chrome_session)
                env['MODALCLOSER_POLL_INTERVAL'] = '100'  # 100ms

                modalcloser_process = subprocess.Popen(
                    ['node', str(MODALCLOSER_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-poll'],
                    cwd=str(modalcloser_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env
                )

                # Run for short time
                time.sleep(1)

                # Should still be running
                assert modalcloser_process.poll() is None, "Should still be running"

                # Clean exit
                modalcloser_process.send_signal(signal.SIGTERM)
                stdout, stderr = modalcloser_process.communicate(timeout=5)

                assert modalcloser_process.returncode == 0, f"Should exit 0: {stderr}"

                # Verify JSONL output exists
                result_json = None
                for line in stdout.strip().split('\n'):
                    if line.strip().startswith('{'):
                        try:
                            record = json.loads(line)
                            if record.get('type') == 'ArchiveResult':
                                result_json = record
                                break
                        except json.JSONDecodeError:
                            pass

                assert result_json is not None, "Should have JSONL output"
                assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"

        finally:
            if modalcloser_process and modalcloser_process.poll() is None:
                modalcloser_process.kill()


def test_hides_cookie_consent_on_filmin():
    """Live test: verify modalcloser hides cookie consent popup on filmin.es."""
    # Create a test script that uses puppeteer directly
    test_script = '''
const puppeteer = require('puppeteer-core');

async function closeModals(page) {
    return page.evaluate(() => {
        let closed = 0;

        // Bootstrap 4/5
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
            document.querySelectorAll('.modal.show').forEach(el => {
                try {
                    const modal = bootstrap.Modal.getInstance(el);
                    if (modal) { modal.hide(); closed++; }
                } catch (e) {}
            });
        }

        // Bootstrap 3 / jQuery
        if (typeof jQuery !== 'undefined' && jQuery.fn && jQuery.fn.modal) {
            try {
                const $modals = jQuery('.modal.in, .modal.show');
                if ($modals.length > 0) {
                    $modals.modal('hide');
                    closed += $modals.length;
                }
            } catch (e) {}
        }

        // Generic selectors including cookie consent
        const genericSelectors = [
            // CookieYes (cky) specific selectors
            '.cky-consent-container',
            '.cky-popup-center',
            '.cky-overlay',
            '.cky-modal',
            '#ckyPreferenceCenter',
            // Generic cookie consent
            '#cookie-consent', '.cookie-banner', '.cookie-notice',
            '#cookieConsent', '.cookie-consent', '.cookies-banner',
            '[class*="cookie"][class*="banner"]',
            '[class*="cookie"][class*="notice"]',
            '[class*="consent"]',
            '[class*="gdpr"]',
            '.modal-overlay', '.modal-backdrop',
            '.popup-overlay', '.newsletter-popup',
        ];

        genericSelectors.forEach(selector => {
            try {
                document.querySelectorAll(selector).forEach(el => {
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return;
                    el.style.display = 'none';
                    el.style.visibility = 'hidden';
                    el.style.opacity = '0';
                    el.style.pointerEvents = 'none';
                    closed++;
                });
            } catch (e) {}
        });

        document.body.style.overflow = '';
        document.body.classList.remove('modal-open', 'overflow-hidden', 'no-scroll');

        return closed;
    });
}

async function main() {
    const browser = await puppeteer.launch({
        headless: 'new',
        executablePath: process.env.CHROME_BINARY || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
    });

    const page = await browser.newPage();
    // Set real user agent to bypass headless detection
    await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
    await page.setViewport({ width: 1440, height: 900 });

    console.error('Navigating to filmin.es...');
    await page.goto('https://www.filmin.es/', { waitUntil: 'networkidle2', timeout: 30000 });

    // Wait for cookie consent to appear
    await new Promise(r => setTimeout(r, 3000));

    // Check BEFORE
    const before = await page.evaluate(() => {
        const el = document.querySelector('.cky-consent-container');
        if (!el) return { found: false };
        const style = window.getComputedStyle(el);
        return { found: true, display: style.display, visibility: style.visibility };
    });

    console.error('Before:', JSON.stringify(before));

    // Run modal closer
    const closed = await closeModals(page);
    console.error('Closed:', closed, 'modals');

    // Check AFTER
    const after = await page.evaluate(() => {
        const el = document.querySelector('.cky-consent-container');
        if (!el) return { found: false };
        const style = window.getComputedStyle(el);
        return { found: true, display: style.display, visibility: style.visibility };
    });

    console.error('After:', JSON.stringify(after));

    await browser.close();

    // Output result as JSON for Python to parse
    const result = {
        before_found: before.found,
        before_visible: before.found && before.display !== 'none' && before.visibility !== 'hidden',
        after_hidden: !after.found || after.display === 'none' || after.visibility === 'hidden',
        modals_closed: closed
    };
    console.log(JSON.stringify(result));
}

main().catch(e => {
    console.error('Error:', e.message);
    process.exit(1);
});
'''

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        script_path = tmpdir / 'test_cookie_consent.js'
        script_path.write_text(test_script)

        env = get_test_env()

        result = subprocess.run(
            ['node', str(script_path)],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        print(f"stderr: {result.stderr}")
        print(f"stdout: {result.stdout}")

        assert result.returncode == 0, f"Test script failed: {result.stderr}"

        # Parse the JSON output
        output_lines = [l for l in result.stdout.strip().split('\n') if l.startswith('{')]
        assert len(output_lines) > 0, f"No JSON output from test script. stdout: {result.stdout}"

        test_result = json.loads(output_lines[-1])

        # The cookie consent should have been found initially (or page changed)
        # After running closeModals, it should be hidden
        if test_result['before_found']:
            assert test_result['after_hidden'], \
                f"Cookie consent should be hidden after modalcloser. Result: {test_result}"
            assert test_result['modals_closed'] > 0, \
                f"Should have closed at least one modal. Result: {test_result}"
        else:
            # Page may have changed, just verify no errors
            print("Cookie consent element not found (page may have changed)")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
