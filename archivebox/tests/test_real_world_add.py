import os
import sqlite3
import subprocess
from pathlib import Path


def _find_snapshot_dir(data_dir: Path, snapshot_id: str) -> Path | None:
    candidates = {snapshot_id}
    if len(snapshot_id) == 32:
        hyphenated = f"{snapshot_id[:8]}-{snapshot_id[8:12]}-{snapshot_id[12:16]}-{snapshot_id[16:20]}-{snapshot_id[20:]}"
        candidates.add(hyphenated)
    elif len(snapshot_id) == 36 and '-' in snapshot_id:
        candidates.add(snapshot_id.replace('-', ''))

    for needle in candidates:
        for path in data_dir.rglob(needle):
            if path.is_dir():
                return path
    return None


def _find_html_with_text(root: Path, needle: str) -> list[Path]:
    hits: list[Path] = []
    for path in root.rglob("*.htm*"):
        if not path.is_file():
            continue
        try:
            if needle in path.read_text(errors="ignore"):
                hits.append(path)
        except Exception:
            continue
    return hits


def test_add_real_world_example_domain(tmp_path):
    os.chdir(tmp_path)
    tmp_short = Path("/tmp") / f"abx-{tmp_path.name}"
    tmp_short.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TMP_DIR"] = str(tmp_short)
    env["ARCHIVEBOX_ALLOW_NO_UNIX_SOCKETS"] = "true"

    init = subprocess.run(
        ["archivebox", "init"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert init.returncode == 0, f"archivebox init failed: {init.stderr}"

    result = subprocess.run(
        ["archivebox", "add", "https://example.com"],
        capture_output=True,
        text=True,
        timeout=900,
        env=env,
    )
    assert result.returncode == 0, (
        "archivebox add failed.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    conn = sqlite3.connect(tmp_path / "index.sqlite3")
    c = conn.cursor()
    snapshot_row = c.execute(
        "SELECT id, url, title FROM core_snapshot WHERE url = ?",
        ("https://example.com",),
    ).fetchone()
    assert snapshot_row is not None, "Snapshot for https://example.com not found in DB"
    snapshot_id, snapshot_url, snapshot_title = snapshot_row
    assert snapshot_title and "Example Domain" in snapshot_title, (
        f"Expected title to contain Example Domain, got: {snapshot_title}"
    )

    failed_results = c.execute(
        "SELECT COUNT(*) FROM core_archiveresult WHERE snapshot_id = ? AND status = 'failed'",
        (snapshot_id,),
    ).fetchone()[0]
    assert failed_results == 0, "Some archive results failed for example.com snapshot"

    binary_workers = c.execute(
        "SELECT COUNT(*) FROM machine_process WHERE process_type = 'worker' AND worker_type = 'binary'"
    ).fetchone()[0]
    assert binary_workers > 0, "Expected BinaryWorker to run installs via BinaryMachine"

    failed_binary_workers = c.execute(
        "SELECT COUNT(*) FROM machine_process WHERE process_type = 'worker' AND worker_type = 'binary' "
        "AND exit_code IS NOT NULL AND exit_code != 0"
    ).fetchone()[0]
    assert failed_binary_workers == 0, "BinaryWorker reported non-zero exit codes"

    queued_binaries = c.execute(
        "SELECT name FROM machine_binary WHERE status != 'installed'"
    ).fetchall()
    assert not queued_binaries, f"Some binaries did not install: {queued_binaries}"
    conn.close()

    snapshot_dir = _find_snapshot_dir(tmp_path, str(snapshot_id))
    assert snapshot_dir is not None, "Snapshot output directory not found"

    title_path = snapshot_dir / "title" / "title.txt"
    assert title_path.exists(), f"Missing title output: {title_path}"
    assert "Example Domain" in title_path.read_text(errors="ignore")

    html_sources = []
    for candidate in ("wget", "singlefile", "dom"):
        for candidate_dir in (snapshot_dir / candidate, *snapshot_dir.glob(f"*_{candidate}")):
            if candidate_dir.exists():
                html_sources.extend(_find_html_with_text(candidate_dir, "Example Domain"))
    assert len(html_sources) >= 2, (
        "Expected HTML outputs from multiple extractors to contain Example Domain "
        f"(found {len(html_sources)})."
    )

    text_hits = 0
    for path in (
        *snapshot_dir.glob("*_readability/content.txt"),
        snapshot_dir / "readability" / "content.txt",
    ):
        if path.exists() and "Example Domain" in path.read_text(errors="ignore"):
            text_hits += 1
    for path in (
        *snapshot_dir.glob("*_htmltotext/htmltotext.txt"),
        snapshot_dir / "htmltotext" / "htmltotext.txt",
    ):
        if path.exists() and "Example Domain" in path.read_text(errors="ignore"):
            text_hits += 1
    assert text_hits >= 2, (
        "Expected multiple text extractors to contain Example Domain "
        f"(readability/htmltotext hits={text_hits})."
    )
