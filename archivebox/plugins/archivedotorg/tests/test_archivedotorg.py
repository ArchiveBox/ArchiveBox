"""
Integration tests for archivedotorg plugin

Tests verify standalone archive.org extractor execution.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

PLUGIN_DIR = Path(__file__).parent.parent
ARCHIVEDOTORG_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_archivedotorg.*'), None)
TEST_URL = 'https://example.com'

def test_hook_script_exists():
    assert ARCHIVEDOTORG_HOOK.exists()

def test_submits_to_archivedotorg():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, str(ARCHIVEDOTORG_HOOK), '--url', TEST_URL, '--snapshot-id', 'test789'],
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

        if result.returncode == 0:
            # Success - should have ArchiveResult
            assert result_json, "Should have ArchiveResult JSONL output on success"
            assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"
        else:
            # Transient error - no JSONL output, just stderr
            assert not result_json, "Should NOT emit JSONL on transient error"
            assert result.stderr, "Should have error message in stderr"

def test_config_save_archivedotorg_false_skips():
    with tempfile.TemporaryDirectory() as tmpdir:
        import os
        env = os.environ.copy()
        env['ARCHIVEDOTORG_ENABLED'] = 'False'

        result = subprocess.run(
            [sys.executable, str(ARCHIVEDOTORG_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir, capture_output=True, text=True, env=env, timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when feature disabled: {result.stderr}"

        # Feature disabled - temporary failure, should NOT emit JSONL
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
            [sys.executable, str(ARCHIVEDOTORG_HOOK), '--url', TEST_URL, '--snapshot-id', 'testtimeout'],
            cwd=tmpdir, capture_output=True, text=True, env=env, timeout=30
        )

        # Timeout is a transient error - should exit 1 with no JSONL
        assert result.returncode in (0, 1), "Should complete without hanging"

        # If it timed out (exit 1), should have no JSONL output
        if result.returncode == 1:
            jsonl_lines = [line for line in result.stdout.strip().split('\n')
                          if line.strip().startswith('{')]
            assert len(jsonl_lines) == 0, "Should not emit JSONL on timeout (transient error)"

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
