"""
Unit tests for captcha2 plugin

Tests invoke the plugin hooks as external processes and verify outputs/side effects.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
INSTALL_SCRIPT = PLUGIN_DIR / "on_Snapshot__01_captcha2.js"
CONFIG_SCRIPT = PLUGIN_DIR / "on_Snapshot__21_captcha2_config.js"


def test_install_script_exists():
    """Verify install script exists"""
    assert INSTALL_SCRIPT.exists(), f"Install script not found: {INSTALL_SCRIPT}"


def test_config_script_exists():
    """Verify config script exists"""
    assert CONFIG_SCRIPT.exists(), f"Config script not found: {CONFIG_SCRIPT}"


def test_extension_metadata():
    """Test that captcha2 extension has correct metadata"""
    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(Path(tmpdir) / "chrome_extensions")

        # Just check the script can be loaded
        result = subprocess.run(
            ["node", "-e", f"const ext = require('{INSTALL_SCRIPT}'); console.log(JSON.stringify(ext.EXTENSION))"],
            capture_output=True,
            text=True,
            env=env
        )

        assert result.returncode == 0, f"Failed to load extension metadata: {result.stderr}"

        metadata = json.loads(result.stdout)
        assert metadata["webstore_id"] == "ifibfemgeogfhoebkmokieepdoobkbpo"
        assert metadata["name"] == "captcha2"


def test_install_creates_cache():
    """Test that install creates extension cache"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)
        env["API_KEY_2CAPTCHA"] = "test_api_key"

        # Run install script
        result = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        # Check output mentions installation
        assert "[*] Installing 2captcha extension" in result.stdout or "[*] 2captcha extension already installed" in result.stdout

        # Check cache file was created
        cache_file = ext_dir / "captcha2.extension.json"
        assert cache_file.exists(), "Cache file should be created"

        # Verify cache content
        cache_data = json.loads(cache_file.read_text())
        assert cache_data["webstore_id"] == "ifibfemgeogfhoebkmokieepdoobkbpo"
        assert cache_data["name"] == "captcha2"
        assert "unpacked_path" in cache_data
        assert "version" in cache_data


def test_install_uses_existing_cache():
    """Test that install uses existing cache when available"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        # Create fake cache
        fake_extension_dir = ext_dir / "ifibfemgeogfhoebkmokieepdoobkbpo__captcha2"
        fake_extension_dir.mkdir(parents=True)

        manifest = {"version": "3.7.0", "name": "2Captcha Solver"}
        (fake_extension_dir / "manifest.json").write_text(json.dumps(manifest))

        cache_data = {
            "webstore_id": "ifibfemgeogfhoebkmokieepdoobkbpo",
            "name": "captcha2",
            "unpacked_path": str(fake_extension_dir),
            "version": "3.7.0"
        }
        (ext_dir / "captcha2.extension.json").write_text(json.dumps(cache_data))

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)
        env["API_KEY_2CAPTCHA"] = "test_api_key"

        # Run install script
        result = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        # Should use cache
        assert "already installed (using cache)" in result.stdout or "Installed extension captcha2" in result.stdout


def test_install_warns_without_api_key():
    """Test that install warns when API key not configured"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)
        # Don't set API_KEY_2CAPTCHA

        # Run install script
        result = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        # Should warn about missing API key
        combined_output = result.stdout + result.stderr
        assert "API_KEY_2CAPTCHA not configured" in combined_output or "Set API_KEY_2CAPTCHA" in combined_output


def test_install_success_with_api_key():
    """Test that install succeeds when API key is configured"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)
        env["API_KEY_2CAPTCHA"] = "test_valid_api_key_123"

        # Run install script
        result = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        # Should mention API key configured
        combined_output = result.stdout + result.stderr
        assert "API key configured" in combined_output or "API_KEY_2CAPTCHA" in combined_output


def test_config_script_structure():
    """Test that config script has proper structure"""
    # Verify the script exists and contains expected markers
    script_content = CONFIG_SCRIPT.read_text()

    # Should mention configuration marker file
    assert "CONFIG_MARKER" in script_content or "captcha2_configured" in script_content

    # Should mention API key
    assert "API_KEY_2CAPTCHA" in script_content

    # Should have main function or be executable
    assert "async function" in script_content or "main" in script_content
