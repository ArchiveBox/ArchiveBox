"""
Integration tests for dom plugin

Tests verify:
1. Hook script exists
2. Dependencies installed via chrome validation hooks
3. Verify deps with abx-pkg
4. DOM extraction works on https://example.com
5. JSONL output is correct
6. Filesystem output contains actual page content
7. Config options work
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from archivebox.plugins.chrome.tests.chrome_test_helpers import (
    get_test_env,
    get_plugin_dir,
    get_hook_script,
    run_hook_and_parse,
    LIB_DIR,
    NODE_MODULES_DIR,
    PLUGINS_ROOT,
)


PLUGIN_DIR = get_plugin_dir(__file__)
DOM_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_dom.*')
NPM_PROVIDER_HOOK = get_hook_script(PLUGINS_ROOT / 'npm', 'on_Binary__install_using_npm_provider.py')
TEST_URL = 'https://example.com'


def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert DOM_HOOK.exists(), f"Hook not found: {DOM_HOOK}"


def test_verify_deps_with_abx_pkg():
    """Verify dependencies are available via abx-pkg after hook installation."""
    from abx_pkg import Binary, EnvProvider, BinProviderOverrides

    EnvProvider.model_rebuild()

    # Verify node is available
    node_binary = Binary(name='node', binproviders=[EnvProvider()])
    node_loaded = node_binary.load()
    assert node_loaded and node_loaded.abspath, "Node.js required for dom plugin"


def test_extracts_dom_from_example_com():
    """Test full workflow: extract DOM from real example.com via hook."""
    # Prerequisites checked by earlier test

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Run DOM extraction hook
        result = subprocess.run(
            ['node', str(DOM_HOOK), f'--url={TEST_URL}', '--snapshot-id=test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=120
        ,
            env=get_test_env())

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

        # Verify filesystem output (hook writes directly to working dir)
        dom_file = tmpdir / 'output.html'
        assert dom_file.exists(), f"output.html not created. Files: {list(tmpdir.iterdir())}"

        # Verify HTML content contains REAL example.com text
        html_content = dom_file.read_text(errors='ignore')
        assert len(html_content) > 200, f"HTML content too short: {len(html_content)} bytes"
        assert '<html' in html_content.lower(), "Missing <html> tag"
        assert 'example domain' in html_content.lower(), "Missing 'Example Domain' in HTML"
        assert ('this domain' in html_content.lower() or
                'illustrative examples' in html_content.lower()), \
            "Missing example.com description text"


def test_config_save_dom_false_skips():
    """Test that DOM_ENABLED=False exits without emitting JSONL."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        env = os.environ.copy()
        env['DOM_ENABLED'] = 'False'

        result = subprocess.run(
            ['node', str(DOM_HOOK), f'--url={TEST_URL}', '--snapshot-id=test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when feature disabled: {result.stderr}"

        # Feature disabled - temporary failure, should NOT emit JSONL
        assert 'Skipping DOM' in result.stderr or 'False' in result.stderr, "Should log skip reason to stderr"

        # Should NOT emit any JSONL
        jsonl_lines = [line for line in result.stdout.strip().split('\n') if line.strip().startswith('{')]
        assert len(jsonl_lines) == 0, f"Should not emit JSONL when feature disabled, but got: {jsonl_lines}"


def test_staticfile_present_skips():
    """Test that dom skips when staticfile already downloaded."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create directory structure like real ArchiveBox:
        # tmpdir/
        #   staticfile/  <- staticfile extractor output
        #   dom/         <- dom extractor runs here, looks for ../staticfile
        staticfile_dir = tmpdir / 'staticfile'
        staticfile_dir.mkdir()
        (staticfile_dir / 'stdout.log').write_text('{"type":"ArchiveResult","status":"succeeded","output_str":"index.html"}\n')

        dom_dir = tmpdir / 'dom'
        dom_dir.mkdir()

        result = subprocess.run(
            ['node', str(DOM_HOOK), f'--url={TEST_URL}', '--snapshot-id=teststatic'],
            cwd=dom_dir,  # Run from dom subdirectory
            capture_output=True,
            text=True,
            timeout=30
        ,
            env=get_test_env())

        assert result.returncode == 0, "Should exit 0 when permanently skipping"

        # Permanent skip - should emit ArchiveResult with status='skipped'
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

        assert result_json, "Should emit ArchiveResult JSONL for permanent skip"
        assert result_json['status'] == 'skipped', f"Should have status='skipped': {result_json}"
        assert 'staticfile' in result_json.get('output_str', '').lower(), "Should mention staticfile in output_str"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
