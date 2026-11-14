"""Plugin inventory and maintenance commands operate on real retained files."""

import json
import subprocess
import sys

import pytest

from abx_dl.execution import iter_plugin_command
from archivebox.plugins.discovery import get_plugin_catalog
from archivebox.tests.test_storageaudit import hashed_snapshot

pytestmark = pytest.mark.django_db(transaction=True)


def test_artifact_apps_import_without_loading_host_runtimes(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import abx_plugins.plugins.chrome_screencast.app; import abx_plugins.plugins.hashes.app; "
            "import sys; assert not any(name == 'archivebox' or name.startswith('archivebox.') "
            "or name == 'abx_dl' or name.startswith('abx_dl.') for name in sys.modules)",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_inventory_provider_normalizes_and_verifies_saved_hashes(admin_user, tmp_path):
    from archivebox.plugins.discovery import get_snapshot_file_inventory
    from archivebox.misc.serve_static import _load_file_inventory

    snapshot = hashed_snapshot(admin_user, tmp_path, "page.json")
    inventory = get_snapshot_file_inventory(snapshot.output_dir, verify=True)
    saved = json.loads((snapshot.output_dir / "hashes/hashes.json").read_text())
    expected = next(item for item in saved["files"] if item["path"] == "original/page.json")
    assert inventory["original/page.json"] == {"hash": expected["hash"], "size": expected["size"], "is_dir": False}
    assert snapshot.hashes_index["original/page.json"]["size"] == expected["size"]
    assert _load_file_inventory(snapshot.output_dir)["original/page.json"]["hash"] == expected["hash"]
    (snapshot.output_dir / "hashes/hashes.sha256").write_text("0" * 64)
    with pytest.raises(ValueError, match="incomplete|changed"):
        get_snapshot_file_inventory(snapshot.output_dir, verify=True)
    assert get_snapshot_file_inventory(snapshot.output_dir) is not None
    assert get_snapshot_file_inventory(tmp_path / "missing") is None


def test_deduplicate_command_preserves_files_and_rejects_escape(tmp_path):
    command = get_plugin_catalog().find_command("deduplicate")
    source = tmp_path / "retained"
    source.mkdir()
    (source / "first.txt").write_text("retained bytes")
    (source / "second.txt").write_text("retained bytes")
    import hashlib

    digest = hashlib.sha256(b"retained bytes").hexdigest()
    request = {
        "root": str(source),
        "files": [{"path": name, "hash": digest, "size": 14} for name in ("first.txt", "second.txt")],
    }
    output = list(iter_plugin_command(command, stdin=[json.dumps(request)], cwd=tmp_path))
    assert len(output) == 1
    result = json.loads(output[0])
    assert isinstance(result["supported_platform"], bool)
    assert all(type(result[key]) is int and result[key] >= 0 for key in ("attempted_files", "extent_bytes_verified", "failed_files"))
    assert (source / "first.txt").read_bytes() == (source / "second.txt").read_bytes() == b"retained bytes"
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    request["files"] = [{"path": "../outside.txt", "hash": digest, "size": 7}]
    with pytest.raises(subprocess.CalledProcessError):
        list(iter_plugin_command(command, stdin=[json.dumps(request)], cwd=tmp_path))
    assert outside.read_text() == "outside"
