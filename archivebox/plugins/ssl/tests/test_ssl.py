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

from django.test import TestCase

# Import chrome test helpers
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'chrome' / 'tests'))
from chrome_test_helpers import (
    chrome_session,
    CHROME_NAVIGATE_HOOK,
    get_plugin_dir,
    get_hook_script,
)


# Get the path to the SSL hook
PLUGIN_DIR = get_plugin_dir(__file__)
SSL_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_ssl.*')


class TestSSLPlugin(TestCase):
    """Test the SSL plugin with real HTTPS URLs."""

    def test_ssl_hook_exists(self):
        """SSL hook script should exist."""
        self.assertIsNotNone(SSL_HOOK, "SSL hook not found in plugin directory")
        self.assertTrue(SSL_HOOK.exists(), f"Hook not found: {SSL_HOOK}")


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

        with chrome_session(
            self.temp_dir,
            crawl_id='test-ssl-crawl',
            snapshot_id=snapshot_id,
            test_url=test_url,
            navigate=False,
            timeout=30,
        ) as (chrome_process, chrome_pid, snapshot_chrome_dir, env):
            ssl_dir = snapshot_chrome_dir.parent / 'ssl'
            ssl_dir.mkdir(exist_ok=True)

            # Run SSL hook with the active Chrome session (background hook)
            result = subprocess.Popen(
                ['node', str(SSL_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                cwd=str(ssl_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )

            nav_result = subprocess.run(
                ['node', str(CHROME_NAVIGATE_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                cwd=str(snapshot_chrome_dir),
                capture_output=True,
                text=True,
                timeout=120,
                env=env
            )
            self.assertEqual(nav_result.returncode, 0, f"Navigation failed: {nav_result.stderr}")

            # Check for output file
            ssl_output = ssl_dir / 'ssl.jsonl'
            for _ in range(30):
                if ssl_output.exists() and ssl_output.stat().st_size > 0:
                    break
                time.sleep(1)

            if result.poll() is None:
                result.terminate()
                try:
                    stdout, stderr = result.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    result.kill()
                    stdout, stderr = result.communicate()
            else:
                stdout, stderr = result.communicate()

            ssl_data = None

            # Try parsing from file first
            if ssl_output.exists():
                with open(ssl_output) as f:
                    content = f.read().strip()
                    if content.startswith('{'):
                        try:
                            ssl_data = json.loads(content)
                        except json.JSONDecodeError:
                            pass

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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
