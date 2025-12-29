"""
Integration tests for htmltotext plugin

Tests verify standalone htmltotext extractor execution.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

PLUGIN_DIR = Path(__file__).parent.parent
HTMLTOTEXT_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_htmltotext.*'), None)
TEST_URL = 'https://example.com'

def test_hook_script_exists():
    assert HTMLTOTEXT_HOOK.exists()

def test_extracts_text_from_html():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        # Create HTML source
        (tmpdir / 'singlefile').mkdir()
        (tmpdir / 'singlefile' / 'singlefile.html').write_text('<html><body><h1>Example Domain</h1><p>This domain is for examples.</p></body></html>')

        result = subprocess.run(
            [sys.executable, str(HTMLTOTEXT_HOOK), '--url', TEST_URL, '--snapshot-id', 'test789'],
            cwd=tmpdir, capture_output=True, text=True, timeout=30
        )

        assert result.returncode == 0, f"Extraction failed: {result.stderr}"

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
        assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"

        # Verify output file (hook writes to current directory)
        output_file = tmpdir / 'htmltotext.txt'
        assert output_file.exists(), f"htmltotext.txt not created. Files: {list(tmpdir.iterdir())}"
        content = output_file.read_text()
        assert len(content) > 0, "Content should not be empty"
        assert 'Example Domain' in content, "Should contain text from HTML"

def test_fails_gracefully_without_html():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, str(HTMLTOTEXT_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir, capture_output=True, text=True, timeout=30
        )

        # Should exit with non-zero or emit failure JSONL
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

        if result_json:
            # Should report failure or skip since no HTML source
            assert result_json['status'] in ['failed', 'skipped'], f"Should fail or skip without HTML: {result_json}"

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
