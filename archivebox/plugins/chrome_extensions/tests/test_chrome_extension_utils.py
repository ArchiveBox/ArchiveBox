"""
Unit tests for chrome_extension_utils.js

Tests invoke the script as an external process and verify outputs/side effects.
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parent.parent / "chrome_extension_utils.js"


def test_script_exists():
    """Verify the script file exists and is executable via node"""
    assert SCRIPT_PATH.exists(), f"Script not found: {SCRIPT_PATH}"


def test_get_extension_id():
    """Test extension ID computation from path"""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = "/path/to/extension"

        # Run script with test path
        result = subprocess.run(
            ["node", str(SCRIPT_PATH), "getExtensionId", test_path],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"

        extension_id = result.stdout.strip()

        # Should return 32-character ID with only letters a-p
        assert len(extension_id) == 32
        assert all(c in 'abcdefghijklmnop' for c in extension_id)


def test_get_extension_id_consistency():
    """Test that same path produces same ID"""
    test_path = "/path/to/extension"

    result1 = subprocess.run(
        ["node", str(SCRIPT_PATH), "getExtensionId", test_path],
        capture_output=True,
        text=True
    )

    result2 = subprocess.run(
        ["node", str(SCRIPT_PATH), "getExtensionId", test_path],
        capture_output=True,
        text=True
    )

    assert result1.returncode == 0
    assert result2.returncode == 0
    assert result1.stdout.strip() == result2.stdout.strip()


def test_get_extension_id_different_paths():
    """Test that different paths produce different IDs"""
    result1 = subprocess.run(
        ["node", str(SCRIPT_PATH), "getExtensionId", "/path1"],
        capture_output=True,
        text=True
    )

    result2 = subprocess.run(
        ["node", str(SCRIPT_PATH), "getExtensionId", "/path2"],
        capture_output=True,
        text=True
    )

    assert result1.returncode == 0
    assert result2.returncode == 0
    assert result1.stdout.strip() != result2.stdout.strip()


def test_load_extension_manifest():
    """Test loading extension manifest.json"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "test_extension"
        ext_dir.mkdir()

        # Create manifest
        manifest = {
            "manifest_version": 3,
            "name": "Test Extension",
            "version": "1.0.0"
        }
        (ext_dir / "manifest.json").write_text(json.dumps(manifest))

        # Load manifest via script
        result = subprocess.run(
            ["node", str(SCRIPT_PATH), "loadExtensionManifest", str(ext_dir)],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        loaded = json.loads(result.stdout)

        assert loaded["manifest_version"] == 3
        assert loaded["name"] == "Test Extension"
        assert loaded["version"] == "1.0.0"


def test_load_extension_manifest_missing():
    """Test loading manifest from non-existent directory"""
    with tempfile.TemporaryDirectory() as tmpdir:
        nonexistent = Path(tmpdir) / "nonexistent"

        result = subprocess.run(
            ["node", str(SCRIPT_PATH), "loadExtensionManifest", str(nonexistent)],
            capture_output=True,
            text=True
        )

        # Should return null/empty for missing manifest
        assert result.returncode == 0
        assert result.stdout.strip() in ("null", "")


def test_load_extension_manifest_invalid_json():
    """Test handling of invalid JSON in manifest"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "test_extension"
        ext_dir.mkdir()

        # Write invalid JSON
        (ext_dir / "manifest.json").write_text("invalid json content")

        result = subprocess.run(
            ["node", str(SCRIPT_PATH), "loadExtensionManifest", str(ext_dir)],
            capture_output=True,
            text=True
        )

        # Should handle gracefully
        assert result.returncode == 0
        assert result.stdout.strip() in ("null", "")


def test_get_extension_launch_args_empty():
    """Test launch args with no extensions"""
    result = subprocess.run(
        ["node", str(SCRIPT_PATH), "getExtensionLaunchArgs", "[]"],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0
    args = json.loads(result.stdout)
    assert args == []


def test_get_extension_launch_args_single():
    """Test launch args with single extension"""
    extensions = [{
        "webstore_id": "abcd1234",
        "unpacked_path": "/path/to/extension"
    }]

    result = subprocess.run(
        ["node", str(SCRIPT_PATH), "getExtensionLaunchArgs", json.dumps(extensions)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0
    args = json.loads(result.stdout)

    assert len(args) == 4
    assert args[0] == "--load-extension=/path/to/extension"
    assert args[1] == "--allowlisted-extension-id=abcd1234"
    assert args[2] == "--allow-legacy-extension-manifests"
    assert args[3] == "--disable-extensions-auto-update"


def test_get_extension_launch_args_multiple():
    """Test launch args with multiple extensions"""
    extensions = [
        {"webstore_id": "ext1", "unpacked_path": "/path/ext1"},
        {"webstore_id": "ext2", "unpacked_path": "/path/ext2"},
        {"webstore_id": "ext3", "unpacked_path": "/path/ext3"}
    ]

    result = subprocess.run(
        ["node", str(SCRIPT_PATH), "getExtensionLaunchArgs", json.dumps(extensions)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0
    args = json.loads(result.stdout)

    assert args[0] == "--load-extension=/path/ext1,/path/ext2,/path/ext3"
    assert args[1] == "--allowlisted-extension-id=ext1,ext2,ext3"


def test_get_extension_launch_args_filter_null_paths():
    """Test that extensions without paths are filtered out"""
    extensions = [
        {"webstore_id": "ext1", "unpacked_path": "/path/ext1"},
        {"webstore_id": "ext2", "unpacked_path": None},
        {"webstore_id": "ext3", "unpacked_path": "/path/ext3"}
    ]

    result = subprocess.run(
        ["node", str(SCRIPT_PATH), "getExtensionLaunchArgs", json.dumps(extensions)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0
    args = json.loads(result.stdout)

    assert args[0] == "--load-extension=/path/ext1,/path/ext3"
    assert args[1] == "--allowlisted-extension-id=ext1,ext3"
