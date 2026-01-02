"""
Tests for the accessibility plugin.

Tests the real accessibility hook with an actual URL to verify
accessibility tree and page outline extraction.
"""

import json
import shutil
import subprocess
import sys
import tempfile
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


# Get the path to the accessibility hook
PLUGIN_DIR = get_plugin_dir(__file__)
ACCESSIBILITY_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_accessibility.*')


class TestAccessibilityPlugin(TestCase):
    """Test the accessibility plugin."""

    def test_accessibility_hook_exists(self):
        """Accessibility hook script should exist."""
        self.assertIsNotNone(ACCESSIBILITY_HOOK, "Accessibility hook not found in plugin directory")
        self.assertTrue(ACCESSIBILITY_HOOK.exists(), f"Hook not found: {ACCESSIBILITY_HOOK}")


@pytest.mark.skipif(not chrome_available(), reason="Chrome not installed")
class TestAccessibilityWithChrome(TestCase):
    """Integration tests for accessibility plugin with Chrome."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_accessibility_extracts_page_outline(self):
        """Accessibility hook should extract headings and accessibility tree."""
        test_url = 'https://example.com'
        snapshot_id = 'test-accessibility-snapshot'

        try:
            with chrome_session(
                self.temp_dir,
                crawl_id='test-accessibility-crawl',
                snapshot_id=snapshot_id,
                test_url=test_url,
                navigate=True,
                timeout=30,
            ) as (chrome_process, chrome_pid, snapshot_chrome_dir):
                # Get environment and run the accessibility hook
                env = get_test_env()
                env['CHROME_HEADLESS'] = 'true'

                # Run accessibility hook with the active Chrome session
                result = subprocess.run(
                    ['node', str(ACCESSIBILITY_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                    cwd=str(snapshot_chrome_dir),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=env
                )

                # Check for output file
                accessibility_output = snapshot_chrome_dir / 'accessibility.json'

                accessibility_data = None

                # Try parsing from file first
                if accessibility_output.exists():
                    with open(accessibility_output) as f:
                        try:
                            accessibility_data = json.load(f)
                        except json.JSONDecodeError:
                            pass

                # Verify hook ran successfully
                self.assertEqual(result.returncode, 0, f"Hook failed: {result.stderr}")
                self.assertNotIn('Traceback', result.stderr)

                # example.com has headings, so we should get accessibility data
                self.assertIsNotNone(accessibility_data, "No accessibility data was generated")

                # Verify we got page outline data
                self.assertIn('headings', accessibility_data, f"Missing headings: {accessibility_data}")
                self.assertIn('url', accessibility_data, f"Missing url: {accessibility_data}")

        except RuntimeError as e:
            if 'Chrome' in str(e) or 'CDP' in str(e):
                self.skipTest(f"Chrome session setup failed: {e}")
            raise


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
