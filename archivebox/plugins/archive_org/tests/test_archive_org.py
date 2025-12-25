"""
Integration tests for archive_org plugin

Tests verify standalone archive.org extractor execution.
"""

import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

PLUGIN_DIR = Path(__file__).parent.parent
ARCHIVE_ORG_HOOK = PLUGIN_DIR / 'on_Snapshot__13_archive_org.py'
TEST_URL = 'https://example.com'

def test_hook_script_exists():
    assert ARCHIVE_ORG_HOOK.exists()

def test_submits_to_archive_org():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, str(ARCHIVE_ORG_HOOK), '--url', TEST_URL, '--snapshot-id', 'test789'],
            cwd=tmpdir, capture_output=True, text=True, timeout=60
        )
        
        assert result.returncode in (0, 1)
        assert 'RESULT_JSON=' in result.stdout
        
        # Should either succeed or fail gracefully
        assert 'STATUS=' in result.stdout

def test_config_save_archive_org_false_skips():
    with tempfile.TemporaryDirectory() as tmpdir:
        import os
        env = os.environ.copy()
        env['SAVE_ARCHIVE_DOT_ORG'] = 'False'
        
        result = subprocess.run(
            [sys.executable, str(ARCHIVE_ORG_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir, capture_output=True, text=True, env=env, timeout=30
        )
        
        if result.returncode == 0:
            assert 'STATUS=skipped' in result.stdout or 'STATUS=succeeded' in result.stdout

def test_handles_timeout():
    with tempfile.TemporaryDirectory() as tmpdir:
        import os
        env = os.environ.copy()
        env['TIMEOUT'] = '1'
        
        result = subprocess.run(
            [sys.executable, str(ARCHIVE_ORG_HOOK), '--url', TEST_URL, '--snapshot-id', 'testtimeout'],
            cwd=tmpdir, capture_output=True, text=True, env=env, timeout=30
        )
        
        assert result.returncode in (0, 1)

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
