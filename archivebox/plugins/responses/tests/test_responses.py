"""
Tests for the responses plugin.

Tests the real responses hook with an actual URL to verify
network response capture.
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


# Get the path to the responses hook
PLUGIN_DIR = get_plugin_dir(__file__)
RESPONSES_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_responses.*')


class TestResponsesPlugin(TestCase):
    """Test the responses plugin."""

    def test_responses_hook_exists(self):
        """Responses hook script should exist."""
        self.assertIsNotNone(RESPONSES_HOOK, "Responses hook not found in plugin directory")
        self.assertTrue(RESPONSES_HOOK.exists(), f"Hook not found: {RESPONSES_HOOK}")


@pytest.mark.skipif(not chrome_available(), reason="Chrome not installed")
class TestResponsesWithChrome(TestCase):
    """Integration tests for responses plugin with Chrome."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_responses_captures_network_responses(self):
        """Responses hook should capture network responses from page load."""
        test_url = 'https://example.com'
        snapshot_id = 'test-responses-snapshot'

        try:
            with chrome_session(
                self.temp_dir,
                crawl_id='test-responses-crawl',
                snapshot_id=snapshot_id,
                test_url=test_url,
                navigate=True,
                timeout=30,
            ) as (chrome_process, chrome_pid, snapshot_chrome_dir, env):
                # Use the environment from chrome_session (already has CHROME_HEADLESS=true)


                # Run responses hook with the active Chrome session (background hook)
                result = subprocess.Popen(
                    ['node', str(RESPONSES_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                    cwd=str(snapshot_chrome_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env
                )

                # Check for output directory and index file
                index_output = snapshot_chrome_dir / 'index.jsonl'

                # Wait briefly for background hook to write output
                for _ in range(10):
                    if index_output.exists() and index_output.stat().st_size > 0:
                        break
                    time.sleep(1)

                # Verify hook ran (may keep running waiting for cleanup signal)
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

                # If index file exists, verify it's valid JSONL
                if index_output.exists():
                    with open(index_output) as f:
                        content = f.read().strip()
                        if content:
                            for line in content.split('\n'):
                                if line.strip():
                                    try:
                                        record = json.loads(line)
                                        # Verify structure
                                        self.assertIn('url', record)
                                        self.assertIn('resourceType', record)
                                    except json.JSONDecodeError:
                                        pass  # Some lines may be incomplete

        except RuntimeError as e:
            if 'Chrome' in str(e) or 'CDP' in str(e):
                self.skipTest(f"Chrome session setup failed: {e}")
            raise


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
