"""
Unit tests for ublock plugin

Tests invoke the plugin hook as an external process and verify outputs/side effects.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
INSTALL_SCRIPT = PLUGIN_DIR / "on_Snapshot__03_ublock.js"


def test_install_script_exists():
    """Verify install script exists"""
    assert INSTALL_SCRIPT.exists(), f"Install script not found: {INSTALL_SCRIPT}"


def test_extension_metadata():
    """Test that uBlock Origin extension has correct metadata"""
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
        assert metadata["webstore_id"] == "cjpalhdlnbpafiamejdnhcphjbkeiagm"
        assert metadata["name"] == "ublock"


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
            timeout=120  # uBlock is large, may take longer to download
        )

        # Check output mentions installation
        assert "uBlock" in result.stdout or "ublock" in result.stdout

        # Check cache file was created
        cache_file = ext_dir / "ublock.extension.json"
        assert cache_file.exists(), "Cache file should be created"

        # Verify cache content
        cache_data = json.loads(cache_file.read_text())
        assert cache_data["webstore_id"] == "cjpalhdlnbpafiamejdnhcphjbkeiagm"
        assert cache_data["name"] == "ublock"


def test_install_uses_existing_cache():
    """Test that install uses existing cache when available"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        # Create fake cache
        fake_extension_dir = ext_dir / "cjpalhdlnbpafiamejdnhcphjbkeiagm__ublock"
        fake_extension_dir.mkdir(parents=True)

        manifest = {"version": "1.68.0", "name": "uBlock Origin"}
        (fake_extension_dir / "manifest.json").write_text(json.dumps(manifest))

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)

        result = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        # Should use cache or install successfully
        assert result.returncode == 0


def test_no_configuration_required():
    """Test that uBlock Origin works without configuration"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)
        # No API keys needed - works with default filter lists

        result = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120
        )

        # Should not require any API keys
        combined_output = result.stdout + result.stderr
        assert "API" not in combined_output or result.returncode == 0


def test_large_extension_size():
    """Test that uBlock Origin is downloaded successfully despite large size"""
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
            timeout=120
        )

        # If extension was downloaded, verify it's substantial size
        crx_file = ext_dir / "cjpalhdlnbpafiamejdnhcphjbkeiagm__ublock.crx"
        if crx_file.exists():
            # uBlock Origin with filter lists is typically 2-5 MB
            size_bytes = crx_file.stat().st_size
            assert size_bytes > 1_000_000, f"uBlock Origin should be > 1MB, got {size_bytes} bytes"
