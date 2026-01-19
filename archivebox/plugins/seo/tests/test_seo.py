"""
Tests for the SEO plugin.

Tests the real SEO hook with an actual URL to verify
meta tag extraction.
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


# Get the path to the SEO hook
PLUGIN_DIR = get_plugin_dir(__file__)
SEO_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_seo.*')


class TestSEOPlugin(TestCase):
    """Test the SEO plugin."""

    def test_seo_hook_exists(self):
        """SEO hook script should exist."""
        self.assertIsNotNone(SEO_HOOK, "SEO hook not found in plugin directory")
        self.assertTrue(SEO_HOOK.exists(), f"Hook not found: {SEO_HOOK}")


@pytest.mark.skipif(not chrome_available(), reason="Chrome not installed")
class TestSEOWithChrome(TestCase):
    """Integration tests for SEO plugin with Chrome."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_seo_extracts_meta_tags(self):
        """SEO hook should extract meta tags from a real URL."""
        test_url = 'https://example.com'
        snapshot_id = 'test-seo-snapshot'

        try:
            with chrome_session(
                self.temp_dir,
                crawl_id='test-seo-crawl',
                snapshot_id=snapshot_id,
                test_url=test_url,
                navigate=True,
                timeout=30,
            ) as (chrome_process, chrome_pid, snapshot_chrome_dir, env):
                # Use the environment from chrome_session (already has CHROME_HEADLESS=true)


                # Run SEO hook with the active Chrome session
                result = subprocess.run(
                    ['node', str(SEO_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                    cwd=str(snapshot_chrome_dir),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=env
                )

                # Check for output file
                seo_output = snapshot_chrome_dir / 'seo.json'

                seo_data = None

                # Try parsing from file first
                if seo_output.exists():
                    with open(seo_output) as f:
                        try:
                            seo_data = json.load(f)
                        except json.JSONDecodeError:
                            pass

                # Try parsing from stdout if not in file
                if not seo_data:
                    for line in result.stdout.split('\n'):
                        line = line.strip()
                        if line.startswith('{'):
                            try:
                                record = json.loads(line)
                                # SEO data typically has title, description, or og: tags
                                if any(key in record for key in ['title', 'description', 'og:title', 'canonical']):
                                    seo_data = record
                                    break
                            except json.JSONDecodeError:
                                continue

                # Verify hook ran successfully
                self.assertEqual(result.returncode, 0, f"Hook failed: {result.stderr}")
                self.assertNotIn('Traceback', result.stderr)
                self.assertNotIn('Error:', result.stderr)

                # example.com has a title, so we MUST get SEO data
                self.assertIsNotNone(seo_data, "No SEO data extracted from file or stdout")

                # Verify we got some SEO data
                has_seo_data = any(key in seo_data for key in ['title', 'description', 'og:title', 'canonical', 'meta'])
                self.assertTrue(has_seo_data, f"No SEO data extracted: {seo_data}")

        except RuntimeError as e:
            if 'Chrome' in str(e) or 'CDP' in str(e):
                self.skipTest(f"Chrome session setup failed: {e}")
            raise


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
