"""
Integration tests for archive_org plugin

Tests verify standalone archive.org extractor execution.
"""

import json
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

        # Parse clean JSONL output
        result_json = None
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if line.startswith('{'):
                try:
                    record = json.loads(line)
                    if record.get('type') == 'ArchiveResult':
                        result_json = record
                        break
                except json.JSONDecodeError:
                    pass

        assert result_json, "Should have ArchiveResult JSONL output"
        assert result_json['status'] in ['succeeded', 'failed'], f"Should succeed or fail: {result_json}"

def test_config_save_archive_org_false_skips():
    with tempfile.TemporaryDirectory() as tmpdir:
        import os
        env = os.environ.copy()
        env['SAVE_ARCHIVE_DOT_ORG'] = 'False'

        result = subprocess.run(
            [sys.executable, str(ARCHIVE_ORG_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir, capture_output=True, text=True, env=env, timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when feature disabled: {result.stderr}"

        # Feature disabled - no JSONL emission, just logs to stderr
        assert 'Skipping' in result.stderr or 'False' in result.stderr, "Should log skip reason to stderr"

        # Should NOT emit any JSONL
        jsonl_lines = [line for line in result.stdout.strip().split('\n') if line.strip().startswith('{')]
        assert len(jsonl_lines) == 0, f"Should not emit JSONL when feature disabled, but got: {jsonl_lines}"

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
