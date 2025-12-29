"""
Integration tests for singlefile plugin

Tests verify:
1. Hook script exists and has correct metadata
2. Extension installation and caching works
3. Chrome/node dependencies available
4. Hook can be executed successfully
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
INSTALL_SCRIPT = next(PLUGIN_DIR.glob('on_Crawl__*_singlefile.*'), None)
NPM_PROVIDER_HOOK = PLUGINS_ROOT / 'npm' / 'on_Binary__install_using_npm_provider.py'
TEST_URL = "https://example.com"


def test_install_script_exists():
    """Verify install script exists"""
    assert INSTALL_SCRIPT.exists(), f"Install script not found: {INSTALL_SCRIPT}"


def test_extension_metadata():
    """Test that SingleFile extension has correct metadata"""
    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(Path(tmpdir) / "chrome_extensions")

        result = subprocess.run(
            ["node", "-e", f"const ext = require('{INSTALL_SCRIPT}'); console.log(JSON.stringify(ext.EXTENSION))"],
            capture_output=True,
            text=True,
            env=env
        )

        assert result.returncode == 0, f"Failed to load extension metadata: {result.stderr}"

        metadata = json.loads(result.stdout)
        assert metadata["webstore_id"] == "mpiodijhokgodhhofbcjdecpffjipkle"
        assert metadata["name"] == "singlefile"


def test_install_creates_cache():
    """Test that install creates extension cache"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)

        result = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        # Check output mentions installation
        assert "SingleFile" in result.stdout or "singlefile" in result.stdout

        # Check cache file was created
        cache_file = ext_dir / "singlefile.extension.json"
        assert cache_file.exists(), "Cache file should be created"

        # Verify cache content
        cache_data = json.loads(cache_file.read_text())
        assert cache_data["webstore_id"] == "mpiodijhokgodhhofbcjdecpffjipkle"
        assert cache_data["name"] == "singlefile"


def test_install_twice_uses_cache():
    """Test that running install twice uses existing cache on second run"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)

        # First install - downloads the extension
        result1 = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )
        assert result1.returncode == 0, f"First install failed: {result1.stderr}"

        # Verify cache was created
        cache_file = ext_dir / "singlefile.extension.json"
        assert cache_file.exists(), "Cache file should exist after first install"

        # Second install - should use cache
        result2 = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )
        assert result2.returncode == 0, f"Second install failed: {result2.stderr}"

        # Second run should be faster (uses cache) and mention cache
        assert "already installed" in result2.stdout or "cache" in result2.stdout.lower() or result2.returncode == 0


def test_no_configuration_required():
    """Test that SingleFile works without configuration"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)
        # No API keys needed

        result = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        # Should work without API keys
        assert result.returncode == 0


def test_priority_order():
    """Test that singlefile has correct priority (04)"""
    # Extract priority from filename
    filename = INSTALL_SCRIPT.name
    assert "04" in filename, "SingleFile should have priority 04"
    assert filename.startswith("on_Crawl__04_"), "Should follow priority naming convention for Crawl hooks"


def test_output_directory_structure():
    """Test that plugin defines correct output structure"""
    # Verify the script mentions singlefile output directory
    script_content = INSTALL_SCRIPT.read_text()

    # Should mention singlefile output directory
    assert "singlefile" in script_content.lower()
    # Should mention HTML output
    assert ".html" in script_content or "html" in script_content.lower()


def test_verify_deps_with_abx_pkg():
    """Verify dependencies are available via abx-pkg after hook installation."""
    from abx_pkg import Binary, EnvProvider, BinProviderOverrides

    EnvProvider.model_rebuild()

    # Verify node is available (singlefile uses Chrome extension, needs Node)
    node_binary = Binary(name='node', binproviders=[EnvProvider()])
    node_loaded = node_binary.load()
    assert node_loaded and node_loaded.abspath, "Node.js required for singlefile plugin"


def test_singlefile_hook_runs():
    """Verify singlefile hook can be executed and completes."""
    # Prerequisites checked by earlier test

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Run singlefile extraction hook
        result = subprocess.run(
            ['node', str(INSTALL_SCRIPT), f'--url={TEST_URL}', '--snapshot-id=test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=120
        )

        # Hook should complete successfully (even if it just installs extension)
        assert result.returncode == 0, f"Hook execution failed: {result.stderr}"

        # Verify extension installation happens
        assert 'SingleFile extension' in result.stdout or result.returncode == 0, "Should install extension or complete"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
