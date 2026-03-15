from .fixtures import *
import json as pyjson
import sqlite3
from pathlib import Path


def _find_snapshot_dir(data_dir: Path, snapshot_id: str) -> Path | None:
    candidates = {snapshot_id}
    if len(snapshot_id) == 32:
        candidates.add(f"{snapshot_id[:8]}-{snapshot_id[8:12]}-{snapshot_id[12:16]}-{snapshot_id[16:20]}-{snapshot_id[20:]}")
    elif len(snapshot_id) == 36 and "-" in snapshot_id:
        candidates.add(snapshot_id.replace("-", ""))

    for needle in candidates:
        for path in (data_dir / "users/system/snapshots").rglob(needle):
            if path.is_dir():
                return path
    return None


def _latest_snapshot_dir(data_dir: Path) -> Path:
    conn = sqlite3.connect(data_dir / "index.sqlite3")
    try:
        snapshot_id = conn.execute(
            "SELECT id FROM core_snapshot ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    assert snapshot_id is not None, "Expected a snapshot to be created"
    snapshot_dir = _find_snapshot_dir(data_dir, str(snapshot_id[0]))
    assert snapshot_dir is not None, f"Snapshot output directory not found for {snapshot_id[0]}"
    return snapshot_dir


def _find_plugin_output(snapshot_dir: Path, *patterns: str) -> Path | None:
    for pattern in patterns:
        matches = list(snapshot_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def test_singlefile_works(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_SINGLEFILE": "true"})
    add_process = subprocess.run(
        ['archivebox', 'add', 'https://example.com'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
        timeout=900,
    )
    assert add_process.returncode == 0, add_process.stderr
    snapshot_dir = _latest_snapshot_dir(tmp_path)
    output_file = _find_plugin_output(snapshot_dir, "singlefile/singlefile.html", "*_singlefile/singlefile.html")
    assert output_file is not None and output_file.exists()

def test_readability_works(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_READABILITY": "true"})
    add_process = subprocess.run(
        ['archivebox', 'add', 'https://example.com'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
        timeout=900,
    )
    assert add_process.returncode == 0, add_process.stderr
    snapshot_dir = _latest_snapshot_dir(tmp_path)
    output_file = _find_plugin_output(snapshot_dir, "readability/content.html", "*_readability/content.html")
    assert output_file is not None and output_file.exists()

def test_htmltotext_works(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_HTMLTOTEXT": "true"})
    add_process = subprocess.run(
        ['archivebox', 'add', 'https://example.com'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
        timeout=900,
    )
    assert add_process.returncode == 0, add_process.stderr
    snapshot_dir = _latest_snapshot_dir(tmp_path)
    output_file = _find_plugin_output(snapshot_dir, "htmltotext/htmltotext.txt", "*_htmltotext/htmltotext.txt")
    assert output_file is not None and output_file.exists()

def test_use_node_false_disables_readability_and_singlefile(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_READABILITY": "true", "SAVE_DOM": "true", "SAVE_SINGLEFILE": "true", "USE_NODE": "false"})
    add_process = subprocess.run(['archivebox', 'add', 'https://example.com'],
                                  capture_output=True, env=disable_extractors_dict)
    output_str = add_process.stdout.decode("utf-8")
    assert "> singlefile" not in output_str
    assert "> readability" not in output_str

def test_headers_retrieved(tmp_path, process, disable_extractors_dict):
    disable_extractors_dict.update({"SAVE_HEADERS": "true"})
    add_process = subprocess.run(
        ['archivebox', 'add', 'https://example.com'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
        timeout=900,
    )
    assert add_process.returncode == 0, add_process.stderr
    snapshot_dir = _latest_snapshot_dir(tmp_path)
    output_file = _find_plugin_output(snapshot_dir, "headers/headers.json", "*_headers/headers.json")
    assert output_file is not None and output_file.exists()
    with open(output_file, 'r', encoding='utf-8') as f:
        headers = pyjson.load(f)
    assert 'Content-Type' in headers or 'content-type' in headers
