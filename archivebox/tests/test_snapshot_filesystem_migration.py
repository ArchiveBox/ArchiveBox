from pathlib import Path

import pytest
from django.db import connection

from archivebox.config import CONSTANTS
from archivebox.core.models import Snapshot, SnapshotMigrationError


pytestmark = pytest.mark.django_db(transaction=True)


def _make_legacy_snapshot(snapshot: Snapshot) -> tuple[Path, Path]:
    current_dir = snapshot.get_storage_path_for_version(snapshot._fs_current_version())
    legacy_dir = CONSTANTS.ARCHIVE_DIR / snapshot.timestamp
    Snapshot.objects.filter(pk=snapshot.pk).update(fs_version="0.8.0")
    snapshot.refresh_from_db()
    current_dir.mkdir(parents=True, exist_ok=True)
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "unknown" / "nested").mkdir(parents=True)
    (legacy_dir / "unknown" / "payload.bin").write_bytes(b"filesystem migration payload\x00\xff")
    return legacy_dir, current_dir


def test_ordinary_snapshot_save_does_not_migrate_directories(snapshot):
    legacy_dir, current_dir = _make_legacy_snapshot(snapshot)

    snapshot.title = "Metadata-only update"
    snapshot.save()
    snapshot.refresh_from_db()

    assert snapshot.fs_version == "0.8.0"
    assert legacy_dir.exists()
    assert not (current_dir / "unknown" / "payload.bin").exists()


def test_filesystem_migration_repairs_crawl_link(snapshot):
    legacy_dir, current_dir = _make_legacy_snapshot(snapshot)
    crawl_link = Path(snapshot.crawl.output_dir) / "snapshots" / Snapshot.extract_domain_from_url(snapshot.url) / str(snapshot.id)
    crawl_link.unlink(missing_ok=True)

    snapshot.migrate_filesystem_to_current_version()
    snapshot.refresh_from_db()

    assert snapshot.fs_version == snapshot._fs_current_version()
    assert not legacy_dir.exists()
    assert (current_dir / "unknown" / "payload.bin").read_bytes() == b"filesystem migration payload\x00\xff"
    assert crawl_link.is_symlink()
    assert crawl_link.resolve() == current_dir.resolve()


def test_filesystem_migration_resumes_after_shutdown_before_cleanup(snapshot, monkeypatch):
    legacy_dir, current_dir = _make_legacy_snapshot(snapshot)
    real_cleanup = Snapshot._cleanup_old_migration_dir

    def simulate_shutdown_before_cleanup(self, old_dir, new_dir):
        raise RuntimeError("simulated shutdown")

    monkeypatch.setattr(Snapshot, "_cleanup_old_migration_dir", simulate_shutdown_before_cleanup)
    with pytest.raises(RuntimeError, match="simulated shutdown"):
        snapshot.migrate_filesystem_to_current_version()
    snapshot.refresh_from_db()

    assert snapshot.fs_version == "0.8.0"
    assert legacy_dir.exists()
    assert (current_dir / "unknown" / "payload.bin").read_bytes() == b"filesystem migration payload\x00\xff"

    monkeypatch.setattr(Snapshot, "_cleanup_old_migration_dir", real_cleanup)
    snapshot.migrate_filesystem_to_current_version()
    snapshot.refresh_from_db()

    assert snapshot.fs_version == snapshot._fs_current_version()
    assert not legacy_dir.exists()
    assert (current_dir / "unknown" / "payload.bin").read_bytes() == b"filesystem migration payload\x00\xff"


def test_filesystem_migration_cleans_legacy_source_when_version_is_current(snapshot, monkeypatch):
    legacy_dir, current_dir = _make_legacy_snapshot(snapshot)
    monkeypatch.setattr(Snapshot, "_cleanup_old_migration_dir", lambda *_args: True)
    snapshot.migrate_filesystem_to_current_version()
    snapshot.refresh_from_db()
    assert snapshot.fs_version == snapshot._fs_current_version()
    assert legacy_dir.exists()

    monkeypatch.undo()
    snapshot.migrate_filesystem_to_current_version()

    assert not legacy_dir.exists()
    assert (current_dir / "unknown" / "payload.bin").read_bytes() == b"filesystem migration payload\x00\xff"


def test_fs_version_has_database_index():
    assert Snapshot._meta.get_field("fs_version").db_index is True
    constraints = connection.introspection.get_constraints(connection.cursor(), Snapshot._meta.db_table)
    assert any(index["index"] and index["columns"] == ["fs_version"] for index in constraints.values())


def test_resume_refuses_to_overwrite_changed_legacy_output(snapshot, monkeypatch):
    legacy_dir, current_dir = _make_legacy_snapshot(snapshot)
    monkeypatch.setattr(Snapshot, "_cleanup_old_migration_dir", lambda *_args: True)
    snapshot.migrate_filesystem_to_current_version()
    (legacy_dir / "unknown" / "payload.bin").write_bytes(b"changed after database commit")

    with pytest.raises(SnapshotMigrationError, match="overwrite a different output"):
        snapshot.migrate_filesystem_to_current_version()

    assert legacy_dir.exists()
    assert (current_dir / "unknown" / "payload.bin").read_bytes() == b"filesystem migration payload\x00\xff"


def _hyphenated(path: Path) -> Path:
    import uuid

    return path.with_name(str(uuid.UUID(hex=path.name)))


def test_filesystem_migration_renames_hyphenated_crawl_dir(snapshot):
    """Crawl.output_dir trusts the DB, so migration must move pre-0.9.4 crawl dirs."""
    crawl_dir = Path(snapshot.crawl.output_dir)
    legacy_crawl_dir = _hyphenated(crawl_dir)
    legacy_crawl_dir.mkdir(parents=True)
    (legacy_crawl_dir / "sources.txt").write_text("https://example.com\n", encoding="utf-8")
    Snapshot.objects.filter(pk=snapshot.pk).update(fs_version="0.9.0")
    snapshot.refresh_from_db()

    snapshot.migrate_filesystem_to_current_version()
    snapshot.refresh_from_db()

    assert snapshot.fs_version == snapshot._fs_current_version()
    assert not legacy_crawl_dir.exists()
    assert (crawl_dir / "sources.txt").read_text(encoding="utf-8") == "https://example.com\n"


def test_rescan_moves_hyphenated_dirs_of_current_rows_into_db_paths(snapshot):
    """`update --rescan` makes disk match what request handlers read from the DB."""
    from archivebox.cli.rescan import rescan_snapshots

    Snapshot.objects.filter(pk=snapshot.pk).update(
        status=Snapshot.StatusChoices.SEALED,
        retry_at=None,
        fs_version=Snapshot._fs_current_version(),
    )
    snapshot.refresh_from_db()
    assert not snapshot.fs_migration_needed
    current_dir = Path(snapshot.output_dir)
    crawl_dir = Path(snapshot.crawl.output_dir)
    legacy_dir, legacy_crawl_dir = _hyphenated(current_dir), _hyphenated(crawl_dir)
    (legacy_dir / "wget").mkdir(parents=True)
    (legacy_dir / "wget" / "index.html").write_text("<html>saved</html>", encoding="utf-8")
    legacy_crawl_dir.mkdir(parents=True)
    (legacy_crawl_dir / "sources.txt").write_text("https://example.com\n", encoding="utf-8")
    assert not current_dir.exists() and not crawl_dir.exists()

    stats = rescan_snapshots()

    assert stats["Errors"] == 0
    assert not legacy_dir.exists() and not legacy_crawl_dir.exists()
    assert (current_dir / "wget" / "index.html").read_text(encoding="utf-8") == "<html>saved</html>"
    assert (current_dir / CONSTANTS.JSONL_INDEX_FILENAME).is_file()
    assert (crawl_dir / "sources.txt").read_text(encoding="utf-8") == "https://example.com\n"
    crawl_link = crawl_dir / "snapshots" / Snapshot.extract_domain_from_url(snapshot.url) / str(snapshot.id)
    assert crawl_link.resolve() == current_dir.resolve()
