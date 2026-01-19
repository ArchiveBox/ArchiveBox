"""
Tests for the parse_dom_outlinks plugin.

Tests the real DOM outlinks hook with an actual URL to verify
link extraction and categorization.
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


# Get the path to the parse_dom_outlinks hook
PLUGIN_DIR = get_plugin_dir(__file__)
OUTLINKS_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_parse_dom_outlinks.*')


class TestParseDomOutlinksPlugin(TestCase):
    """Test the parse_dom_outlinks plugin."""

    def test_outlinks_hook_exists(self):
        """DOM outlinks hook script should exist."""
        self.assertIsNotNone(OUTLINKS_HOOK, "DOM outlinks hook not found in plugin directory")
        self.assertTrue(OUTLINKS_HOOK.exists(), f"Hook not found: {OUTLINKS_HOOK}")


@pytest.mark.skipif(not chrome_available(), reason="Chrome not installed")
class TestParseDomOutlinksWithChrome(TestCase):
    """Integration tests for parse_dom_outlinks plugin with Chrome."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_outlinks_extracts_links_from_page(self):
        """DOM outlinks hook should extract and categorize links from page."""
        test_url = 'https://example.com'
        snapshot_id = 'test-outlinks-snapshot'

        try:
            with chrome_session(
                self.temp_dir,
                crawl_id='test-outlinks-crawl',
                snapshot_id=snapshot_id,
                test_url=test_url,
                navigate=True,
                timeout=30,
            ) as (chrome_process, chrome_pid, snapshot_chrome_dir, env):
                # Use the environment from chrome_session (already has CHROME_HEADLESS=true)


                # Run outlinks hook with the active Chrome session
                result = subprocess.run(
                    ['node', str(OUTLINKS_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                    cwd=str(snapshot_chrome_dir),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=env
                )

                # Check for output file
                outlinks_output = snapshot_chrome_dir / 'outlinks.json'

                outlinks_data = None
                json_error = None

                # Try parsing from file first
                if outlinks_output.exists():
                    with open(outlinks_output) as f:
                        try:
                            outlinks_data = json.load(f)
                        except json.JSONDecodeError as e:
                            json_error = str(e)

                # Verify hook ran successfully
                self.assertEqual(result.returncode, 0, f"Hook failed: {result.stderr}")
                self.assertNotIn('Traceback', result.stderr)

                # Verify we got outlinks data with expected categories
                self.assertIsNotNone(outlinks_data, f"No outlinks data found - file missing or invalid JSON: {json_error}")

                self.assertIn('url', outlinks_data, f"Missing url: {outlinks_data}")
                self.assertIn('hrefs', outlinks_data, f"Missing hrefs: {outlinks_data}")
                # example.com has at least one link (to iana.org)
                self.assertIsInstance(outlinks_data['hrefs'], list)

        except RuntimeError as e:
            if 'Chrome' in str(e) or 'CDP' in str(e):
                self.skipTest(f"Chrome session setup failed: {e}")
            raise


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
