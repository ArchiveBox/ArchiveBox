"""Explicit maintenance must count retained bytes without inventing capture results."""

import hashlib
import json
from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.tests.conftest import cli_env, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def test_filesystem_migration_refuses_a_live_server(archivebox_daemon_server):
    server = archivebox_daemon_server(SEARCH_BACKEND_ENGINE="ripgrep", PLUGINS="")
    server.wait_for_workers(("worker_uvicorn", "worker_runner"))
    for args in (["update", "--migrate-only"], ["update", "--rescan"]):
        result = run_archivebox_cmd(args, cwd=server.data_dir, env=server.env)
        assert result.returncode != 0, result.stdout + result.stderr
        assert "Stop the local ArchiveBox server" in result.stdout + result.stderr
    server.wait_for_workers(("worker_uvicorn", "worker_runner"))


def test_maintenance_batch_does_not_duplicate_large_crawl_url_list(initialized_archive):
    import tracemalloc
    from archivebox.cli.archivebox_update import process_all_db_snapshots
    from archivebox.crawls.models import Crawl

    urls = "\n".join(f"https://example.com/legacy-collection/{i:06d}" for i in range(25000))
    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.create(urls=urls, status="sealed", retry_at=None)
        ids = []
        for i in range(32):
            snapshot = Snapshot.objects.create(
                crawl=crawl,
                url=f"https://example.com/legacy-collection/{i:06d}",
                fs_version="0.8.0",
                status="sealed",
                retry_at=None,
            )
            ids.append(snapshot.pk)
        tracemalloc.start()
        try:
            stats = process_all_db_snapshots(batch_size=32)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        # A scan may load one crawl, but must not replicate its entire URL
        # list into every snapshot in a page. This is an allocation bound,
        # independent of the machine's speed or Python's baseline RSS.
        assert peak < 4 * len(urls), f"maintenance allocated {peak:,} bytes for {len(urls):,} bytes of shared crawl URLs"
        assert stats["queued"] == 32
        assert Snapshot.objects.filter(pk__in=ids, fs_version="0.8.0", status="sealed", retry_at__isnull=False).count() == 32
        assert Crawl.objects.get(pk=crawl.pk).urls == urls


def test_rescan_skips_known_unfinished_snapshots_without_changing_them(initialized_archive):
    from archivebox.crawls.models import Crawl

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.create(urls="https://example.com/not-captured")
        snapshot = Snapshot.objects.create(
            url=crawl.urls,
            crawl=crawl,
            status="queued",
            retry_at=None,
            fs_version=Snapshot._fs_current_version(),
        )
        snapshot.output_dir.mkdir(parents=True, exist_ok=True)
        snapshot.write_index_jsonl()
        snapshot_id = snapshot.pk
        index = snapshot.output_dir / "index.jsonl"
        original_index = index.read_bytes()
        original_row = Snapshot.objects.filter(pk=snapshot_id).values().get()

    result = run_archivebox_cmd(["update", "--rescan", "--migrate-only"], cwd=initialized_archive, env=cli_env(disable_extractors=True))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Skipped: 1" in result.stdout
    assert "Errors: 0" in result.stdout
    assert index.read_bytes() == original_index
    with use_archivebox_db(initialized_archive):
        assert Snapshot.objects.filter(pk=snapshot_id).values().get() == original_row
        assert not ArchiveResult.objects.filter(snapshot_id=snapshot_id).exists()


def test_filtered_migration_reports_conflict_and_preserves_both_files(initialized_archive):
    from archivebox.crawls.models import Crawl

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.create(urls="https://example.com/conflict", status="sealed", retry_at=None)
        snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, status="sealed", retry_at=None, fs_version="0.8.0")
        old_dir = snapshot.get_storage_path_for_version("0.8.0")
        new_dir = snapshot.get_storage_path_for_version(Snapshot._fs_current_version())
        for directory, content in ((old_dir, b"original evidence"), (new_dir, b"different evidence")):
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "payload.bin").write_bytes(content)
        snapshot_id, timestamp = snapshot.pk, snapshot.timestamp

    for _ in range(2):
        result = run_archivebox_cmd(
            ["update", "--migrate-only", "--filter-type", "timestamp", timestamp],
            cwd=initialized_archive,
            env=cli_env(disable_extractors=True),
        )
        assert result.returncode != 0, result.stdout + result.stderr
        assert "overwrite a different output" in result.stdout + result.stderr
        assert (old_dir / "payload.bin").read_bytes() == b"original evidence"
        assert (new_dir / "payload.bin").read_bytes() == b"different evidence"
        with use_archivebox_db(initialized_archive):
            assert Snapshot.objects.get(pk=snapshot_id).fs_version == "0.8.0"


@pytest.mark.parametrize("filtered", [True, False])
def test_rescan_counts_resultless_payload_without_recapture(initialized_archive, filtered):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.create(
            urls="https://archivebox.io/tests/preserved-payload",
            created_by_id=get_or_create_system_user_pk(),
            status="sealed",
        )
        selected = Snapshot.objects.create(
            url=crawl.urls,
            crawl=crawl,
            status="sealed",
            retry_at=None,
            fs_version=Snapshot._fs_current_version(),
        )
        other = Snapshot.objects.create(
            url="https://archivebox.io/tests/unselected-payload",
            crawl=crawl,
            status="sealed",
            retry_at=None,
            fs_version=Snapshot._fs_current_version(),
        )
        for snapshot in (selected, other):
            snapshot.output_dir.mkdir(parents=True, exist_ok=True)
            snapshot.write_index_jsonl()
        selected_id, other_id = selected.pk, other.pk
        selected_dir, other_dir = selected.output_dir, other.output_dir
        timestamp = selected.timestamp
        other_modified = other.modified_at

    payload = (Path(__file__).parent / "fixtures/bablosoft-lazy-image/work-1.png").read_bytes()
    (selected_dir / "screenshot.png").write_bytes(payload)
    article = b"<html><title>Preserved capture</title><body>Existing archived content.</body></html>"
    (selected_dir / "output.html").write_bytes(article)
    (selected_dir / "index.html").write_text("<html>Generated archive navigation, not captured output.</html>")
    (selected_dir / ".DS_Store").write_bytes(b"not captured output")
    (other_dir / "untouched.txt").write_bytes(b"other snapshot")
    (selected_dir / "outside-link").symlink_to(other_dir / "untouched.txt")
    expected_size = len(payload) + len(article)
    before_hash = hashlib.sha256(payload).hexdigest()
    args = ["update", "--rescan", "--migrate-only"]
    if filtered:
        args.extend(["--filter-type", "timestamp", timestamp])
    prior_modified = None

    for _ in range(2):
        result = run_archivebox_cmd(args, cwd=initialized_archive, env=cli_env(disable_extractors=True), timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        with use_archivebox_db(initialized_archive):
            refreshed = Snapshot.objects.get(pk=selected_id)
            assert refreshed.output_size == expected_size
            assert refreshed.status == "sealed"
            assert refreshed.retry_at is None
            assert refreshed.downloaded_at is None
            assert not ArchiveResult.objects.filter(snapshot_id=selected_id).exists()
            if prior_modified is not None:
                assert refreshed.modified_at == prior_modified
            prior_modified = refreshed.modified_at
            untouched = Snapshot.objects.get(pk=other_id)
            assert untouched.status == "sealed" and untouched.retry_at is None
            assert not ArchiveResult.objects.filter(snapshot_id=other_id).exists()
            if filtered:
                assert untouched.output_size == 0
                assert untouched.modified_at == other_modified
            else:
                assert untouched.output_size == len(b"other snapshot")
        assert hashlib.sha256((selected_dir / "screenshot.png").read_bytes()).hexdigest() == before_hash
        assert (selected_dir / "output.html").read_bytes() == article
        assert (other_dir / "untouched.txt").read_bytes() == b"other snapshot"
        records = [json.loads(line) for line in (selected_dir / "index.jsonl").read_text().splitlines()]
        assert next(record for record in records if record["type"] == "Snapshot")["output_size"] == expected_size
        assert not any(record["type"] == "ArchiveResult" for record in records)
