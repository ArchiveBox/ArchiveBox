"""
Integration tests for dom plugin

Tests verify:
1. Hook script exists
2. Dependencies installed via chrome_session validation hooks
3. Verify deps with abx-pkg
4. DOM extraction works on https://example.com
5. JSONL output is correct
6. Filesystem output contains actual page content
7. Config options work
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
DOM_HOOK = PLUGIN_DIR / 'on_Snapshot__36_dom.js'
CHROME_VALIDATE_HOOK = PLUGINS_ROOT / 'chrome_session' / 'on_Crawl__00_validate_chrome.py'
NPM_PROVIDER_HOOK = PLUGINS_ROOT / 'npm' / 'on_Dependency__install_using_npm_provider.py'
TEST_URL = 'https://example.com'


def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert DOM_HOOK.exists(), f"Hook not found: {DOM_HOOK}"


def test_chrome_validation_and_install():
    """Test chrome validation hook to install puppeteer-core if needed."""
    # Run chrome validation hook (from chrome_session plugin)
    result = subprocess.run(
        [sys.executable, str(CHROME_VALIDATE_HOOK)],
        capture_output=True,
        text=True,
        timeout=30
    )

    # If exit 1, binary not found - need to install
    if result.returncode == 1:
        # Parse Dependency request from JSONL
        dependency_request = None
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    record = json.loads(line)
                    if record.get('type') == 'Dependency':
                        dependency_request = record
                        break
                except json.JSONDecodeError:
                    pass

        if dependency_request:
            bin_name = dependency_request['bin_name']
            bin_providers = dependency_request['bin_providers']

            # Install via npm provider hook
            install_result = subprocess.run(
                [
                    sys.executable,
                    str(NPM_PROVIDER_HOOK),
                    '--dependency-id', 'test-dep-001',
                    '--bin-name', bin_name,
                    '--bin-providers', bin_providers
                ],
                capture_output=True,
                text=True,
                timeout=600
            )

            assert install_result.returncode == 0, f"Install failed: {install_result.stderr}"

            # Verify installation via JSONL output
            for line in install_result.stdout.strip().split('\n'):
                if line.strip():
                    try:
                        record = json.loads(line)
                        if record.get('type') == 'InstalledBinary':
                            assert record['name'] == bin_name
                            assert record['abspath']
                            break
                    except json.JSONDecodeError:
                        pass
    else:
        # Binary already available, verify via JSONL output
        assert result.returncode == 0, f"Validation failed: {result.stderr}"


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
        )

        assert result.returncode == 0, f"Extraction failed: {result.stderr}"

        # Verify JSONL output
        assert 'STATUS=succeeded' in result.stdout, "Should report success"
        assert 'RESULT_JSON=' in result.stdout, "Should output RESULT_JSON"

        # Parse JSONL result
        result_json = None
        for line in result.stdout.split('\n'):
            if line.startswith('RESULT_JSON='):
                result_json = json.loads(line.split('=', 1)[1])
                break

        assert result_json, "Should have RESULT_JSON"
        assert result_json['extractor'] == 'dom'
        assert result_json['status'] == 'succeeded'
        assert result_json['url'] == TEST_URL

        # Verify filesystem output
        dom_dir = tmpdir / 'dom'
        assert dom_dir.exists(), "Output directory not created"

        dom_file = dom_dir / 'output.html'
        assert dom_file.exists(), "output.html not created"

        # Verify HTML content contains REAL example.com text
        html_content = dom_file.read_text(errors='ignore')
        assert len(html_content) > 200, f"HTML content too short: {len(html_content)} bytes"
        assert '<html' in html_content.lower(), "Missing <html> tag"
        assert 'example domain' in html_content.lower(), "Missing 'Example Domain' in HTML"
        assert ('this domain' in html_content.lower() or
                'illustrative examples' in html_content.lower()), \
            "Missing example.com description text"


def test_config_save_dom_false_skips():
    """Test that SAVE_DOM=False causes skip."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        env = os.environ.copy()
        env['SAVE_DOM'] = 'False'

        result = subprocess.run(
            ['node', str(DOM_HOOK), f'--url={TEST_URL}', '--snapshot-id=test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when skipping: {result.stderr}"
        assert 'STATUS=skipped' in result.stdout, "Should report skipped status"


def test_staticfile_present_skips():
    """Test that dom skips when staticfile already downloaded."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create staticfile directory to simulate staticfile extractor ran
        staticfile_dir = tmpdir / 'staticfile'
        staticfile_dir.mkdir()
        (staticfile_dir / 'index.html').write_text('<html>test</html>')

        result = subprocess.run(
            ['node', str(DOM_HOOK), f'--url={TEST_URL}', '--snapshot-id=teststatic'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0, "Should exit 0 when skipping"
        assert 'STATUS=skipped' in result.stdout, "Should report skipped status"
        assert 'staticfile' in result.stdout.lower(), "Should mention staticfile"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
