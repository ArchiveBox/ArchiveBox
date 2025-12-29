"""
Unit tests for istilldontcareaboutcookies plugin

Tests invoke the plugin hook as an external process and verify outputs/side effects.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
INSTALL_SCRIPT = next(PLUGIN_DIR.glob('on_Crawl__*_istilldontcareaboutcookies.*'), None)


def test_install_script_exists():
    """Verify install script exists"""
    assert INSTALL_SCRIPT.exists(), f"Install script not found: {INSTALL_SCRIPT}"


def test_extension_metadata():
    """Test that extension has correct metadata"""
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
        assert metadata["webstore_id"] == "edibdbjcniadpccecjdfdjjppcpchdlm"
        assert metadata["name"] == "istilldontcareaboutcookies"


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
        assert "Installing" in result.stdout or "installed" in result.stdout or "istilldontcareaboutcookies" in result.stdout

        # Check cache file was created
        cache_file = ext_dir / "istilldontcareaboutcookies.extension.json"
        assert cache_file.exists(), "Cache file should be created"

        # Verify cache content
        cache_data = json.loads(cache_file.read_text())
        assert cache_data["webstore_id"] == "edibdbjcniadpccecjdfdjjppcpchdlm"
        assert cache_data["name"] == "istilldontcareaboutcookies"


def test_install_uses_existing_cache():
    """Test that install uses existing cache when available"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        # Create fake cache
        fake_extension_dir = ext_dir / "edibdbjcniadpccecjdfdjjppcpchdlm__istilldontcareaboutcookies"
        fake_extension_dir.mkdir(parents=True)

        manifest = {"version": "1.1.8", "name": "I still don't care about cookies"}
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
    """Test that extension works without any configuration"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)
        # No special env vars needed - works out of the box

        result = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        # Should not require any API keys or configuration
        assert "API" not in (result.stdout + result.stderr) or result.returncode == 0
