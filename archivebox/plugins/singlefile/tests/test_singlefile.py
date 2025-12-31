"""
Integration tests for singlefile plugin

Tests verify:
1. Hook scripts exist with correct naming
2. CLI-based singlefile extraction works
3. Dependencies available via abx-pkg
4. Output contains valid HTML
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
SNAPSHOT_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_singlefile.py'), None)
TEST_URL = "https://example.com"


def test_snapshot_hook_exists():
    """Verify snapshot extraction hook exists"""
    assert SNAPSHOT_HOOK is not None and SNAPSHOT_HOOK.exists(), f"Snapshot hook not found in {PLUGIN_DIR}"


def test_snapshot_hook_priority():
    """Test that snapshot hook has correct priority (50)"""
    filename = SNAPSHOT_HOOK.name
    assert "50" in filename, "SingleFile snapshot hook should have priority 50"
    assert filename.startswith("on_Snapshot__50_"), "Should follow priority naming convention"


def test_verify_deps_with_abx_pkg():
    """Verify dependencies are available via abx-pkg."""
    from abx_pkg import Binary, EnvProvider

    EnvProvider.model_rebuild()

    # Verify node is available
    node_binary = Binary(name='node', binproviders=[EnvProvider()])
    node_loaded = node_binary.load()
    assert node_loaded and node_loaded.abspath, "Node.js required for singlefile plugin"


def test_singlefile_cli_archives_example_com():
    """Test that singlefile CLI archives example.com and produces valid HTML."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        env = os.environ.copy()
        env['SINGLEFILE_ENABLED'] = 'true'

        # Run singlefile snapshot hook
        result = subprocess.run(
            ['python', str(SNAPSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=120
        )

        assert result.returncode == 0, f"Hook execution failed: {result.stderr}"

        # Verify output file exists
        output_file = tmpdir / 'singlefile.html'
        assert output_file.exists(), f"singlefile.html not created. stdout: {result.stdout}, stderr: {result.stderr}"

        # Verify it contains real HTML
        html_content = output_file.read_text()
        assert len(html_content) > 500, "Output file too small to be valid HTML"
        assert '<!DOCTYPE html>' in html_content or '<html' in html_content, "Output should contain HTML doctype or html tag"
        assert 'Example Domain' in html_content, "Output should contain example.com content"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
