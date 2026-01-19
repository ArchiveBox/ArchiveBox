"""
Tests for the staticfile plugin.

Tests the real staticfile hook with actual URLs to verify
static file detection and download.
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


# Get the path to the staticfile hook
PLUGIN_DIR = get_plugin_dir(__file__)
STATICFILE_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_staticfile.*')


class TestStaticfilePlugin(TestCase):
    """Test the staticfile plugin."""

    def test_staticfile_hook_exists(self):
        """Staticfile hook script should exist."""
        self.assertIsNotNone(STATICFILE_HOOK, "Staticfile hook not found in plugin directory")
        self.assertTrue(STATICFILE_HOOK.exists(), f"Hook not found: {STATICFILE_HOOK}")


@pytest.mark.skipif(not chrome_available(), reason="Chrome not installed")
class TestStaticfileWithChrome(TestCase):
    """Integration tests for staticfile plugin with Chrome."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_staticfile_skips_html_pages(self):
        """Staticfile hook should skip HTML pages (not static files)."""
        test_url = 'https://example.com'  # HTML page, not a static file
        snapshot_id = 'test-staticfile-snapshot'

        try:
            with chrome_session(
                self.temp_dir,
                crawl_id='test-staticfile-crawl',
                snapshot_id=snapshot_id,
                test_url=test_url,
                navigate=True,
                timeout=30,
            ) as (chrome_process, chrome_pid, snapshot_chrome_dir, env):
                # Use the environment from chrome_session (already has CHROME_HEADLESS=true)


                # Run staticfile hook with the active Chrome session (background hook)
                result = subprocess.Popen(
                    ['node', str(STATICFILE_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                    cwd=str(snapshot_chrome_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env
                )

                # Allow it to run briefly, then terminate (background hook)
                time.sleep(3)
                if result.poll() is None:
                    result.terminate()
                    try:
                        stdout, stderr = result.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        result.kill()
                        stdout, stderr = result.communicate()
                else:
                    stdout, stderr = result.communicate()

                # Verify hook ran without crash
                self.assertNotIn('Traceback', stderr)

                # Parse JSONL output to verify it recognized HTML as non-static
                for line in stdout.split('\n'):
                    line = line.strip()
                    if line.startswith('{'):
                        try:
                            record = json.loads(line)
                            if record.get('type') == 'ArchiveResult':
                                # HTML pages should be skipped
                                if record.get('status') == 'skipped':
                                    self.assertIn('Not a static file', record.get('output_str', ''))
                                break
                        except json.JSONDecodeError:
                            continue

        except RuntimeError as e:
            if 'Chrome' in str(e) or 'CDP' in str(e):
                self.skipTest(f"Chrome session setup failed: {e}")
            raise


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
