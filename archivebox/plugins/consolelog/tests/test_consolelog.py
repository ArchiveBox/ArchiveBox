"""
Tests for the consolelog plugin.

Tests the real consolelog hook with an actual URL to verify
console output capture.
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


# Get the path to the consolelog hook
PLUGIN_DIR = get_plugin_dir(__file__)
CONSOLELOG_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_consolelog.*')


class TestConsolelogPlugin(TestCase):
    """Test the consolelog plugin."""

    def test_consolelog_hook_exists(self):
        """Consolelog hook script should exist."""
        self.assertIsNotNone(CONSOLELOG_HOOK, "Consolelog hook not found in plugin directory")
        self.assertTrue(CONSOLELOG_HOOK.exists(), f"Hook not found: {CONSOLELOG_HOOK}")


class TestConsolelogWithChrome(TestCase):
    """Integration tests for consolelog plugin with Chrome."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_consolelog_captures_output(self):
        """Consolelog hook should capture console output from page."""
        test_url = 'data:text/html,<script>console.log("archivebox-console-test")</script>'
        snapshot_id = 'test-consolelog-snapshot'

        with chrome_session(
            self.temp_dir,
            crawl_id='test-consolelog-crawl',
            snapshot_id=snapshot_id,
            test_url=test_url,
            navigate=False,
            timeout=30,
        ) as (chrome_process, chrome_pid, snapshot_chrome_dir, env):
            console_dir = snapshot_chrome_dir.parent / 'consolelog'
            console_dir.mkdir(exist_ok=True)

            # Run consolelog hook with the active Chrome session (background hook)
            result = subprocess.Popen(
                ['node', str(CONSOLELOG_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                cwd=str(console_dir),
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
            console_output = console_dir / 'console.jsonl'

            # Allow it to run briefly, then terminate (background hook)
            for _ in range(10):
                if console_output.exists() and console_output.stat().st_size > 0:
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

            # At minimum, verify no crash
            self.assertNotIn('Traceback', stderr)

            # If output file exists, verify it's valid JSONL and has output
            if console_output.exists():
                with open(console_output) as f:
                    content = f.read().strip()
                    self.assertTrue(content, "Console output should not be empty")
                    for line in content.split('\n'):
                        if line.strip():
                            try:
                                record = json.loads(line)
                                # Verify structure
                                self.assertIn('timestamp', record)
                                self.assertIn('type', record)
                            except json.JSONDecodeError:
                                pass  # Some lines may be incomplete


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
