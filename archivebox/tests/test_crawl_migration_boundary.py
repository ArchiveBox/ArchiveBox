"""Snapshot maintenance must never relocate unrelated historical crawl output."""

from pathlib import Path

import pytest

from archivebox.core.models import Snapshot

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("fs_version", ["0.9.0", "0.9.4", "0.9.5"])
def test_targeted_snapshot_migration_preserves_parent_crawl_tree(snapshot, fs_version):
    from archivebox.config import CONSTANTS
    from archivebox.tests.test_archive_storage_isolation import observe_archive_access

    Snapshot.objects.filter(pk=snapshot.pk).update(fs_version=fs_version)
    snapshot.refresh_from_db()
    current_crawl, legacy_crawl = snapshot.crawl.output_dir_candidates
    untouched = legacy_crawl / "unselected-capture" / "saved.bin"
    untouched.parent.mkdir(parents=True)
    untouched.write_bytes(b"unrelated historical crawl bytes\x00\xff")
    before = untouched.stat()
    snapshot_dir = snapshot.get_storage_path_for_version(snapshot._fs_current_version())
    (snapshot_dir / "wget").mkdir(parents=True)
    (snapshot_dir / "wget" / "index.html").write_text("<html>selected capture</html>")

    with observe_archive_access(CONSTANTS.ARCHIVE_DIR) as touches:
        snapshot.migrate_filesystem_to_current_version()
        snapshot.ensure_crawl_symlink()

    assert not any(touch.startswith("rename(") and str(legacy_crawl) in touch for touch in touches), "\n".join(touches)
    assert untouched.read_bytes() == b"unrelated historical crawl bytes\x00\xff"
    assert untouched.stat().st_ino == before.st_ino
    assert current_crawl.is_symlink()
    assert current_crawl.readlink() == Path(legacy_crawl.name)
    assert (current_crawl / "unselected-capture" / "saved.bin").read_bytes() == untouched.read_bytes()
    crawl_link = current_crawl / "snapshots" / Snapshot.extract_domain_from_url(snapshot.url) / str(snapshot.id)
    assert crawl_link.resolve() == snapshot_dir.resolve()
    snapshot.refresh_from_db()
    assert snapshot.fs_version == snapshot._fs_current_version()
    assert snapshot.crawl.migrate_legacy_output_dir() is False


def test_filtered_migrate_cli_does_not_relocate_parent_or_select_other_snapshots(initialized_archive):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.tests.conftest import cli_env, run_archivebox_cmd
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    selected_url = "https://archivebox.io/tests/selected-migration"
    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.create(urls=selected_url, created_by_id=get_or_create_system_user_pk(), status="sealed")
        selected = Snapshot.objects.create(url=selected_url, crawl=crawl, status="sealed", retry_at=None, fs_version="0.9.4")
        other = Snapshot.objects.create(
            url="https://archivebox.io/tests/unselected-migration",
            crawl=crawl,
            status="sealed",
            retry_at=None,
            fs_version="0.9.4",
        )
        selected_id, other_id = selected.pk, other.pk
        current_crawl, legacy_crawl = crawl.output_dir_candidates
        selected_dir = selected.get_storage_path_for_version(Snapshot._fs_current_version())
    legacy_crawl.mkdir(parents=True)
    historical = legacy_crawl / "historical.bin"
    historical.write_bytes(b"preserved historical bytes")
    historical_inode = historical.stat().st_ino
    (selected_dir / "wget").mkdir(parents=True)
    (selected_dir / "wget" / "index.html").write_text("<html>selected bytes</html>")

    result = run_archivebox_cmd(
        ["update", "--migrate-only", selected_url],
        cwd=initialized_archive,
        env=cli_env(disable_extractors=True),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert historical.read_bytes() == b"preserved historical bytes"
    assert historical.stat().st_ino == historical_inode
    assert current_crawl.is_symlink() and current_crawl.resolve() == legacy_crawl
    assert (selected_dir / "wget" / "index.html").read_text() == "<html>selected bytes</html>"
    with use_archivebox_db(initialized_archive):
        assert Snapshot.objects.get(pk=selected_id).fs_version == Snapshot._fs_current_version()
        untouched = Snapshot.objects.get(pk=other_id)
        assert untouched.fs_version == "0.9.4"
        assert untouched.status == "sealed" and untouched.retry_at is None


def test_cancel_partial_snapshot_keeps_parent_crawl_in_place(snapshot):
    Snapshot.objects.filter(pk=snapshot.pk).update(status="started", fs_version=Snapshot._fs_current_version())
    snapshot.refresh_from_db()
    canonical, legacy = snapshot.crawl.output_dir_candidates
    legacy.mkdir(parents=True)
    (legacy / "historical.bin").write_bytes(b"unrelated capture")
    output = snapshot.output_dir
    output.mkdir(parents=True)
    (output / "partial.txt").write_text("partial capture")
    (output / "finished.pid").write_text("0")

    snapshot.cancel()

    snapshot.refresh_from_db()
    assert snapshot.status == "sealed"
    assert (legacy / "historical.bin").read_bytes() == b"unrelated capture"
    assert (output / "partial.txt").read_text() == "partial capture"
    assert not (output / "finished.pid").exists()
    snapshot.ensure_crawl_symlink()
    assert canonical.is_symlink() and canonical.resolve() == legacy


def test_partial_crawl_move_keeps_both_trees_and_repairs_only_selected_projection(snapshot):
    canonical, legacy = snapshot.crawl.output_dir_candidates
    canonical.mkdir(parents=True)
    legacy.mkdir()
    (canonical / "already-moved.bin").write_bytes(b"current bytes")
    (legacy / "not-moved.bin").write_bytes(b"legacy bytes")
    snapshot_dir = snapshot.get_storage_path_for_version(snapshot._fs_current_version())
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "saved.txt").write_text("selected capture")

    assert snapshot.crawl.migrate_legacy_output_dir() is False
    snapshot.reconcile_filesystem_links()

    assert not canonical.is_symlink()
    assert (canonical / "already-moved.bin").read_bytes() == b"current bytes"
    assert (legacy / "not-moved.bin").read_bytes() == b"legacy bytes"
    assert not (canonical / "not-moved.bin").exists()
    assert not (legacy / "already-moved.bin").exists()
    projection = canonical / "snapshots" / Snapshot.extract_domain_from_url(snapshot.url) / str(snapshot.id)
    assert projection.is_symlink() and projection.resolve() == snapshot_dir.resolve()


def test_canonical_crawl_alias_serves_saved_bytes_and_preserves_file_containment(client, api_admin_user, api_headers):
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(urls="https://archivebox.io/tests/legacy-crawl", created_by=api_admin_user)
    canonical, legacy = crawl.output_dir_candidates
    legacy.mkdir(parents=True)
    (legacy / "saved.txt").write_bytes(b"historical saved bytes")
    outside = legacy.parent / "outside.txt"
    outside.write_bytes(b"private bytes")
    (legacy / "escape.txt").symlink_to(outside)
    assert crawl.migrate_legacy_output_dir() is True
    (canonical / "new.txt").write_bytes(b"new crawl bytes")
    assert (legacy / "new.txt").read_bytes() == b"new crawl bytes"

    response = client.get(f"/api/v1/crawls/crawl/{crawl.id}/files/saved.txt", **api_headers)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"historical saved bytes"
    for path in ("escape.txt", "../outside.txt"):
        assert client.get(f"/api/v1/crawls/crawl/{crawl.id}/files/{path}", **api_headers).status_code == 404
    assert outside.read_bytes() == b"private bytes"
