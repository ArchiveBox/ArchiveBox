"""
Tests for the SSL plugin.

Tests the real SSL hook with an actual HTTPS URL to verify
certificate information extraction.
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
    get_plugin_dir,
    get_hook_script,
)


def chrome_available() -> bool:
    """Check if Chrome/Chromium is available."""
    for name in ['chromium', 'chromium-browser', 'google-chrome', 'chrome']:
        if shutil.which(name):
            return True
    return False


# Get the path to the SSL hook
PLUGIN_DIR = get_plugin_dir(__file__)
SSL_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_ssl.*')


class TestSSLPlugin(TestCase):
    """Test the SSL plugin with real HTTPS URLs."""

    def test_ssl_hook_exists(self):
        """SSL hook script should exist."""
        self.assertIsNotNone(SSL_HOOK, "SSL hook not found in plugin directory")
        self.assertTrue(SSL_HOOK.exists(), f"Hook not found: {SSL_HOOK}")


@pytest.mark.skipif(not chrome_available(), reason="Chrome not installed")
class TestSSLWithChrome(TestCase):
    """Integration tests for SSL plugin with Chrome."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ssl_extracts_certificate_from_https_url(self):
        """SSL hook should extract certificate info from a real HTTPS URL."""
        test_url = 'https://example.com'
        snapshot_id = 'test-ssl-snapshot'

        try:
            with chrome_session(
                self.temp_dir,
                crawl_id='test-ssl-crawl',
                snapshot_id=snapshot_id,
                test_url=test_url,
                navigate=True,
                timeout=30,
            ) as (chrome_process, chrome_pid, snapshot_chrome_dir, env):
                # Use the environment from chrome_session (already has CHROME_HEADLESS=true)


                # Run SSL hook with the active Chrome session (background hook)
                result = subprocess.Popen(
                    ['node', str(SSL_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
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

                # Check for output file
                ssl_output = snapshot_chrome_dir / 'ssl.jsonl'

                ssl_data = None

                # Try parsing from file first
                if ssl_output.exists():
                    with open(ssl_output) as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith('{'):
                                try:
                                    ssl_data = json.loads(line)
                                    break
                                except json.JSONDecodeError:
                                    continue

                # Try parsing from stdout if not in file
                if not ssl_data:
                    for line in stdout.split('\n'):
                        line = line.strip()
                        if line.startswith('{'):
                            try:
                                record = json.loads(line)
                                if 'protocol' in record or 'issuer' in record or record.get('type') == 'SSL':
                                    ssl_data = record
                                    break
                            except json.JSONDecodeError:
                                continue

                # Verify hook ran successfully
                self.assertNotIn('Traceback', stderr)
                self.assertNotIn('Error:', stderr)

                # example.com uses HTTPS, so we MUST get SSL certificate data
                self.assertIsNotNone(ssl_data, "No SSL data extracted from HTTPS URL")

                # Verify we got certificate info
                self.assertIn('protocol', ssl_data, f"SSL data missing protocol: {ssl_data}")
                self.assertTrue(
                    ssl_data['protocol'].startswith('TLS') or ssl_data['protocol'].startswith('SSL'),
                    f"Unexpected protocol: {ssl_data['protocol']}"
                )

        except RuntimeError as e:
            if 'Chrome' in str(e) or 'CDP' in str(e):
                self.skipTest(f"Chrome session setup failed: {e}")
            raise


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
