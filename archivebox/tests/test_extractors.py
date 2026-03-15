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
        for path in data_dir.rglob(needle):
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


def _latest_plugin_result(data_dir: Path, plugin: str) -> tuple[str, str, dict]:
    conn = sqlite3.connect(data_dir / "index.sqlite3")
    try:
        row = conn.execute(
            "SELECT snapshot_id, status, output_files FROM core_archiveresult "
            "WHERE plugin = ? ORDER BY created_at DESC LIMIT 1",
            (plugin,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, f"Expected an ArchiveResult row for plugin={plugin}"
    output_files = row[2]
    if isinstance(output_files, str):
        output_files = pyjson.loads(output_files or "{}")
    output_files = output_files or {}
    return str(row[0]), str(row[1]), output_files


def _plugin_output_paths(data_dir: Path, plugin: str) -> list[Path]:
    snapshot_id, status, output_files = _latest_plugin_result(data_dir, plugin)
    assert status == "succeeded", f"Expected {plugin} ArchiveResult to succeed, got {status}"
    assert output_files, f"Expected {plugin} ArchiveResult to record output_files"

    snapshot_dir = _find_snapshot_dir(data_dir, snapshot_id)
    assert snapshot_dir is not None, f"Snapshot output directory not found for {snapshot_id}"

    plugin_dir = snapshot_dir / plugin
    output_paths = [plugin_dir / rel_path for rel_path in output_files.keys()]
    missing_paths = [path for path in output_paths if not path.exists()]
    assert not missing_paths, f"Expected plugin outputs to exist on disk, missing: {missing_paths}"
    return output_paths


def _archivebox_env(base_env: dict, data_dir: Path) -> dict:
    env = base_env.copy()
    tmp_dir = Path("/tmp") / f"abx-{data_dir.name}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    env["TMP_DIR"] = str(tmp_dir)
    env["ARCHIVEBOX_ALLOW_NO_UNIX_SOCKETS"] = "true"
    return env


def test_singlefile_works(tmp_path, process, disable_extractors_dict):
    data_dir = Path.cwd()
    env = _archivebox_env(disable_extractors_dict, data_dir)
    env.update({"SAVE_SINGLEFILE": "true"})
    add_process = subprocess.run(
        ['archivebox', 'add', '--plugins=singlefile', 'https://example.com'],
        capture_output=True,
        text=True,
        env=env,
        timeout=900,
    )
    assert add_process.returncode == 0, add_process.stderr
    output_files = _plugin_output_paths(data_dir, "singlefile")
    assert any(path.suffix in (".html", ".htm") for path in output_files)

def test_readability_works(tmp_path, process, disable_extractors_dict):
    data_dir = Path.cwd()
    env = _archivebox_env(disable_extractors_dict, data_dir)
    env.update({"SAVE_SINGLEFILE": "true", "SAVE_READABILITY": "true"})
    add_process = subprocess.run(
        ['archivebox', 'add', '--plugins=singlefile,readability', 'https://example.com'],
        capture_output=True,
        text=True,
        env=env,
        timeout=900,
    )
    assert add_process.returncode == 0, add_process.stderr
    output_files = _plugin_output_paths(data_dir, "readability")
    assert any(path.suffix in (".html", ".htm") for path in output_files)

def test_htmltotext_works(tmp_path, process, disable_extractors_dict):
    data_dir = Path.cwd()
    env = _archivebox_env(disable_extractors_dict, data_dir)
    env.update({"SAVE_WGET": "true", "SAVE_HTMLTOTEXT": "true"})
    add_process = subprocess.run(
        ['archivebox', 'add', '--plugins=wget,htmltotext', 'https://example.com'],
        capture_output=True,
        text=True,
        env=env,
        timeout=900,
    )
    assert add_process.returncode == 0, add_process.stderr
    output_files = _plugin_output_paths(data_dir, "htmltotext")
    assert any(path.suffix == ".txt" for path in output_files)

def test_use_node_false_disables_readability_and_singlefile(tmp_path, process, disable_extractors_dict):
    env = _archivebox_env(disable_extractors_dict, Path.cwd())
    env.update({"SAVE_READABILITY": "true", "SAVE_DOM": "true", "SAVE_SINGLEFILE": "true", "USE_NODE": "false"})
    add_process = subprocess.run(['archivebox', 'add', '--plugins=readability,dom,singlefile', 'https://example.com'],
                                  capture_output=True, env=env)
    output_str = add_process.stdout.decode("utf-8")
    assert "> singlefile" not in output_str
    assert "> readability" not in output_str

def test_headers_retrieved(tmp_path, process, disable_extractors_dict):
    data_dir = Path.cwd()
    env = _archivebox_env(disable_extractors_dict, data_dir)
    env.update({"SAVE_HEADERS": "true"})
    add_process = subprocess.run(
        ['archivebox', 'add', '--plugins=headers', 'https://example.com'],
        capture_output=True,
        text=True,
        env=env,
        timeout=900,
    )
    assert add_process.returncode == 0, add_process.stderr
    output_files = _plugin_output_paths(data_dir, "headers")
    output_file = next((path for path in output_files if path.suffix == ".json"), None)
    assert output_file is not None, f"Expected headers output_files to include a JSON file, got: {output_files}"
    with open(output_file, 'r', encoding='utf-8') as f:
        headers = pyjson.load(f)
    response_headers = headers.get("response_headers") or headers.get("headers") or {}
    assert isinstance(response_headers, dict), f"Expected response_headers dict, got: {response_headers!r}"
    assert 'Content-Type' in response_headers or 'content-type' in response_headers
