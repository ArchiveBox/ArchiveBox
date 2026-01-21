"""
Tests for the DNS plugin.

Tests the real DNS hook with an actual URL to verify
DNS resolution capture.
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


# Get the path to the DNS hook
PLUGIN_DIR = get_plugin_dir(__file__)
DNS_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_dns.*')


class TestDNSPlugin(TestCase):
    """Test the DNS plugin."""

    def test_dns_hook_exists(self):
        """DNS hook script should exist."""
        self.assertIsNotNone(DNS_HOOK, "DNS hook not found in plugin directory")
        self.assertTrue(DNS_HOOK.exists(), f"Hook not found: {DNS_HOOK}")


class TestDNSWithChrome(TestCase):
    """Integration tests for DNS plugin with Chrome."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_dns_records_captured(self):
        """DNS hook should capture DNS records from a real URL."""
        test_url = 'https://example.com'
        snapshot_id = 'test-dns-snapshot'

        with chrome_session(
            self.temp_dir,
            crawl_id='test-dns-crawl',
            snapshot_id=snapshot_id,
            test_url=test_url,
            navigate=False,
            timeout=30,
        ) as (_process, _pid, snapshot_chrome_dir, env):
            dns_dir = snapshot_chrome_dir.parent / 'dns'
            dns_dir.mkdir(exist_ok=True)

            result = subprocess.Popen(
                ['node', str(DNS_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                cwd=str(dns_dir),
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

            dns_output = dns_dir / 'dns.jsonl'
            for _ in range(30):
                if dns_output.exists() and dns_output.stat().st_size > 0:
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

            self.assertNotIn('Traceback', stderr)

            self.assertTrue(dns_output.exists(), "dns.jsonl not created")
            content = dns_output.read_text().strip()
            self.assertTrue(content, "DNS output should not be empty")

            records = []
            for line in content.split('\n'):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

            self.assertTrue(records, "No DNS records parsed")
            has_ip_record = any(r.get('hostname') and r.get('ip') for r in records)
            self.assertTrue(has_ip_record, f"No DNS record with hostname + ip: {records}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
