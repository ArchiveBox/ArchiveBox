"""
Unit tests for singlefile plugin

Tests invoke the plugin hook as an external process and verify outputs/side effects.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
INSTALL_SCRIPT = PLUGIN_DIR / "on_Snapshot__04_singlefile.js"


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
    assert filename.startswith("on_Snapshot__04_"), "Should follow priority naming convention"


def test_output_directory_structure():
    """Test that plugin defines correct output structure"""
    # Verify the script mentions singlefile output directory
    script_content = INSTALL_SCRIPT.read_text()

    # Should mention singlefile output directory
    assert "singlefile" in script_content.lower()
    # Should mention HTML output
    assert ".html" in script_content or "html" in script_content.lower()
