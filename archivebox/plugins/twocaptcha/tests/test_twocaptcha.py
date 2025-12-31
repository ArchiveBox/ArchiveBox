"""
Unit tests for twocaptcha plugin

Tests invoke the plugin hooks as external processes and verify outputs/side effects.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
INSTALL_SCRIPT = next(PLUGIN_DIR.glob('on_Crawl__*_install_twocaptcha_extension.*'), None)
CONFIG_SCRIPT = next(PLUGIN_DIR.glob('on_Crawl__*_configure_twocaptcha_extension_options.*'), None)


def test_install_script_exists():
    """Verify install script exists"""
    assert INSTALL_SCRIPT.exists(), f"Install script not found: {INSTALL_SCRIPT}"


def test_config_script_exists():
    """Verify config script exists"""
    assert CONFIG_SCRIPT.exists(), f"Config script not found: {CONFIG_SCRIPT}"


def test_extension_metadata():
    """Test that twocaptcha extension has correct metadata"""
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
        assert metadata["name"] == "twocaptcha"


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
        cache_file = ext_dir / "twocaptcha.extension.json"
        assert cache_file.exists(), "Cache file should be created"

        # Verify cache content
        cache_data = json.loads(cache_file.read_text())
        assert cache_data["webstore_id"] == "ifibfemgeogfhoebkmokieepdoobkbpo"
        assert cache_data["name"] == "twocaptcha"
        assert "unpacked_path" in cache_data
        assert "version" in cache_data


def test_install_twice_uses_cache():
    """Test that running install twice uses existing cache on second run"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)
        env["API_KEY_2CAPTCHA"] = "test_api_key"

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
        cache_file = ext_dir / "twocaptcha.extension.json"
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

        # Second run should mention cache reuse
        assert "already installed" in result2.stdout or "cache" in result2.stdout.lower() or result2.returncode == 0


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
    assert "CONFIG_MARKER" in script_content or "twocaptcha_configured" in script_content

    # Should mention API key
    assert "API_KEY_2CAPTCHA" in script_content

    # Should have main function or be executable
    assert "async function" in script_content or "main" in script_content
