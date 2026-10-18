import json
import os

from archivebox.misc.serve_static import _load_hash_map


def test_replay_hash_cache_releases_old_manifests(tmp_path):
    first = None
    newest = None
    for index in range(256):
        snapshot = tmp_path / str(index)
        hashes = snapshot / "hashes" / "hashes.json"
        hashes.parent.mkdir(parents=True)
        hashes.write_text(json.dumps({"files": [{"path": "screenshot/screenshot.png", "hash": str(index)}]}))
        loaded = _load_hash_map(snapshot)
        assert loaded == {"screenshot/screenshot.png": str(index)}
        if index == 0:
            first = loaded
        newest = loaded

    assert _load_hash_map(tmp_path / "255") is newest
    reloaded = _load_hash_map(tmp_path / "0")
    assert reloaded == first
    assert reloaded is not first


def test_replay_hash_cache_refreshes_changed_manifest(tmp_path):
    hashes = tmp_path / "hashes" / "hashes.json"
    hashes.parent.mkdir()
    hashes.write_text(json.dumps({"files": [{"path": "singlefile/singlefile.html", "hash": "before"}]}))
    old_stat = hashes.stat()
    assert _load_hash_map(tmp_path) == {"singlefile/singlefile.html": "before"}
    hashes.write_text(json.dumps({"files": [{"path": "singlefile/singlefile.html", "hash": "after"}]}))
    os.utime(hashes, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns + 1_000_000_000))
    assert _load_hash_map(tmp_path) == {"singlefile/singlefile.html": "after"}


def test_replay_hash_cache_does_not_retain_failed_reads(tmp_path):
    hashes = tmp_path / "hashes" / "hashes.json"
    hashes.parent.mkdir()
    hashes.write_text("{")
    old_stat = hashes.stat()
    assert _load_hash_map(tmp_path) is None
    hashes.write_text(json.dumps({"files": [{"path": "screenshot/screenshot.png", "hash": "complete"}]}))
    os.utime(hashes, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert _load_hash_map(tmp_path) == {"screenshot/screenshot.png": "complete"}
