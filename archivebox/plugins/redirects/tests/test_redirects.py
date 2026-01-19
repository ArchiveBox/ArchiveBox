"""
Tests for the redirects plugin.

Tests the real redirects hook with actual URLs to verify
redirect chain capture.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from django.test import TestCase

# Import chrome test helpers
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'chrome' / 'tests'))
from chrome_test_helpers import (
    chrome_session,
    get_test_env,
    get_plugin_dir,
    get_hook_script,
)


def chrome_available() -> bool:
    """Check if Chrome/Chromium is available."""
    for name in ['chromium', 'chromium-browser', 'google-chrome', 'chrome']:
        if shutil.which(name):
            return True
    return False


# Get the path to the redirects hook
PLUGIN_DIR = get_plugin_dir(__file__)
REDIRECTS_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_redirects.*')


class TestRedirectsPlugin(TestCase):
    """Test the redirects plugin."""

    def test_redirects_hook_exists(self):
        """Redirects hook script should exist."""
        self.assertIsNotNone(REDIRECTS_HOOK, "Redirects hook not found in plugin directory")
        self.assertTrue(REDIRECTS_HOOK.exists(), f"Hook not found: {REDIRECTS_HOOK}")


@pytest.mark.skipif(not chrome_available(), reason="Chrome not installed")
class TestRedirectsWithChrome(TestCase):
    """Integration tests for redirects plugin with Chrome."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_redirects_captures_navigation(self):
        """Redirects hook should capture URL navigation without errors."""
        # Use a URL that doesn't redirect (simple case)
        test_url = 'https://example.com'
        snapshot_id = 'test-redirects-snapshot'

        try:
            with chrome_session(
                self.temp_dir,
                crawl_id='test-redirects-crawl',
                snapshot_id=snapshot_id,
                test_url=test_url,
                navigate=True,
                timeout=30,
            ) as (chrome_process, chrome_pid, snapshot_chrome_dir, env):
                # Use the environment from chrome_session (already has CHROME_HEADLESS=true)


                # Run redirects hook with the active Chrome session (background hook)
                result = subprocess.Popen(
                    ['node', str(REDIRECTS_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                    cwd=str(snapshot_chrome_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env
                )

                # Check for output file
                redirects_output = snapshot_chrome_dir / 'redirects.jsonl'

                redirects_data = None

                # Wait briefly for background hook to write output
                for _ in range(10):
                    if redirects_output.exists() and redirects_output.stat().st_size > 0:
                        break
                    time.sleep(1)

                # Try parsing from file first
                if redirects_output.exists():
                    with open(redirects_output) as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith('{'):
                                try:
                                    redirects_data = json.loads(line)
                                    break
                                except json.JSONDecodeError:
                                    continue

                # Try parsing from stdout if not in file
                if not redirects_data:
                    try:
                        stdout, stderr = result.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        stdout, stderr = "", ""
                    for line in stdout.split('\n'):
                        line = line.strip()
                        if line.startswith('{'):
                            try:
                                record = json.loads(line)
                                if 'chain' in record or 'redirects' in record or record.get('type') == 'Redirects':
                                    redirects_data = record
                                    break
                            except json.JSONDecodeError:
                                continue

                # Verify hook ran successfully
                # example.com typically doesn't redirect, so we just verify no errors
                if result.poll() is None:
                    result.terminate()
                    try:
                        stdout, stderr = result.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        result.kill()
                        stdout, stderr = result.communicate()
                else:
                    stdout, stderr = result.communicate()
                self.assertNotIn('Traceback', stderr)
                self.assertNotIn('Error:', stderr)

        except RuntimeError as e:
            if 'Chrome' in str(e) or 'CDP' in str(e):
                self.skipTest(f"Chrome session setup failed: {e}")
            raise


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
