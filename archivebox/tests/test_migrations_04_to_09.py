"""End-to-end migration coverage from the oldest Django ArchiveBox schema."""

import json
import sqlite3

from .migrations_helpers import (
    SCHEMA_0_4,
    create_data_dir_structure,
    current_snapshot_dir,
    filesystem_manifest,
    run_archivebox_migration_cmd,
    seed_0_4_data,
)


LEGACY_OUTPUTS = {
    "title": ("title/title.txt", b"Example Domain\n"),
    "favicon": ("favicon/favicon.ico", b"\x00\x00\x01\x00legacy-icon"),
    "wget": ("wget/example.com/index.html", b"<html><body>legacy wget</body></html>"),
    "singlefile": ("singlefile/singlefile.html", b"<html><body>legacy singlefile</body></html>"),
    "pdf": ("pdf/output.pdf", b"%PDF-1.4\n% legacy pdf\n"),
    "screenshot": ("screenshot/screenshot.png", b"\x89PNG\r\n\x1a\nlegacy screenshot"),
    "dom": ("dom/output.html", b"<html><body>legacy dom</body></html>"),
    "readability": ("readability/content.html", b"<article>legacy readability</article>"),
    "mercury": ("mercury/content.html", b"<article>legacy mercury</article>"),
    "git": ("git/repository/HEAD", b"ref: refs/heads/main\n"),
    "media": ("media/video.info.json", b'{"title":"legacy media"}'),
    "headers": ("headers/headers.json", b'{"Content-Type":"text/html"}'),
    "archivedotorg": ("archivedotorg/location.txt", b"https://web.archive.org/example"),
}


def test_oldest_django_collection_migrates_end_to_end_without_data_loss(tmp_path):
    """Exercise the same init/update/status/list sequence used by an upgrading user."""
    create_data_dir_structure(tmp_path)
    db_path = tmp_path / "index.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA_0_4)
    original = seed_0_4_data(db_path)

    # DEBUG=True is common in old ArchiveBox.conf files and exercises Django's
    # debug cursor while every historical data migration runs.
    (tmp_path / "ArchiveBox.conf").write_text("[SERVER_CONFIG]\nDEBUG = True\n")

    original_trees = {}
    for index, snapshot in enumerate(original["snapshots"]):
        if snapshot["timestamp"] is None:
            continue
        snapshot_dir = tmp_path / "archive" / snapshot["timestamp"]
        snapshot_dir.mkdir(parents=True)
        history = {}
        if index == 0:
            for offset, (extractor, (relative_path, payload)) in enumerate(LEGACY_OUTPUTS.items()):
                output_path = snapshot_dir / relative_path
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(payload)
                history[extractor] = [
                    {
                        "cmd": [extractor, "--version"],
                        "cmd_version": "legacy-1.0",
                        "pwd": str(snapshot_dir),
                        "start_ts": f"2024-01-01T12:00:{offset:02d}",
                        "end_ts": f"2024-01-01T12:01:{offset:02d}",
                        "status": "succeeded",
                        "output": relative_path,
                    },
                ]

            (snapshot_dir / "unknown-plugin" / "duplicate-output").mkdir(parents=True)
            (snapshot_dir / "unknown-plugin" / "duplicate-output" / "payload.bin").write_bytes(b"unknown payload\x00\xff")
            (snapshot_dir / "unknown-plugin" / "duplicate-output" / "payload-link").symlink_to("payload.bin")
            (snapshot_dir / "unknown-empty-dir" / "nested").mkdir(parents=True)

        legacy_index = {
            "url": snapshot["url"],
            "timestamp": snapshot["timestamp"],
            "title": snapshot["title"],
            "tags": snapshot["tags"],
            "history": history,
            "custom_legacy_metadata": {"must": "survive"},
        }
        (snapshot_dir / "index.json").write_text(json.dumps(legacy_index, indent=2, sort_keys=True))
        original_trees[snapshot["timestamp"]] = filesystem_manifest(snapshot_dir)

    result = run_archivebox_migration_cmd(tmp_path, ["init"], timeout=90)
    assert result.returncode == 0, result.stderr
    assert "received a naive datetime" not in result.stderr
    for pass_number in (1, 2):
        result = run_archivebox_migration_cmd(tmp_path, ["update"], timeout=180)
        assert result.returncode == 0, f"Update pass {pass_number} failed: {result.stderr}"

    for command in (["status"], ["list", "--json"]):
        result = run_archivebox_migration_cmd(tmp_path, command, timeout=60)
        assert result.returncode == 0, result.stderr

    for timestamp, expected_tree in original_trees.items():
        legacy_dir = tmp_path / "archive" / timestamp
        assert not legacy_dir.exists()
        migrated_tree = filesystem_manifest(current_snapshot_dir(tmp_path, db_path, timestamp))
        assert {path: migrated_tree.get(path) for path in expected_tree} == expected_tree

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0] == len(original["snapshots"])
        assert connection.execute("SELECT COUNT(*) FROM core_archiveresult WHERE hook_name = ''").fetchone()[0] == len(LEGACY_OUTPUTS)
        assert connection.execute("SELECT COUNT(*) FROM core_archiveresult WHERE hook_name = '' AND process_id IS NOT NULL").fetchone()[
            0
        ] == len(
            LEGACY_OUTPUTS,
        )
        migrated_plugins = {
            plugin
            for (plugin,) in connection.execute(
                "SELECT plugin FROM core_archiveresult WHERE hook_name = ''",
            )
        }
        assert migrated_plugins == set(LEGACY_OUTPUTS)

        expected_tags = {tag.strip() for tags in original["tags_str"] for tag in tags.split(",")}
        assert {name for (name,) in connection.execute("SELECT name FROM core_tag")} == expected_tags

        migrated_snapshots = {
            url: title
            for url, title in connection.execute(
                "SELECT url, title FROM core_snapshot",
            )
        }
        assert migrated_snapshots == {snapshot["url"]: snapshot["title"] for snapshot in original["snapshots"]}
        missing_timestamp_snapshot = next(snapshot for snapshot in original["snapshots"] if snapshot["timestamp"] is None)
        assert connection.execute(
            "SELECT timestamp FROM core_snapshot WHERE url = ?",
            (missing_timestamp_snapshot["url"],),
        ).fetchone() == (missing_timestamp_snapshot["id"],)
