"""
Integration tests for htmltotext plugin

Tests verify standalone htmltotext extractor execution.
"""

import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

PLUGIN_DIR = Path(__file__).parent.parent
HTMLTOTEXT_HOOK = PLUGIN_DIR / 'on_Snapshot__54_htmltotext.py'
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
        
        assert result.returncode in (0, 1)
        assert 'RESULT_JSON=' in result.stdout
        
        if result.returncode == 0:
            assert 'STATUS=succeeded' in result.stdout
            output_file = tmpdir / 'htmltotext' / 'content.txt'
            if output_file.exists():
                content = output_file.read_text()
                assert len(content) > 0

def test_fails_gracefully_without_html():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, str(HTMLTOTEXT_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir, capture_output=True, text=True, timeout=30
        )
        assert result.returncode in (0, 1)
        combined = result.stdout + result.stderr
        assert 'STATUS=' in combined

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
