import errno
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from .fixtures import disable_extractors_dict, process

FIXTURES = (disable_extractors_dict, process)


def test_update_imports_orphaned_snapshots(tmp_path, process, disable_extractors_dict):
    """Test that archivebox update imports real legacy archive directories."""
    legacy_timestamp = "1710000000"
    legacy_dir = tmp_path / "archive" / legacy_timestamp
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "singlefile.html").write_text("<html>example</html>")
    (legacy_dir / "index.json").write_text(
        json.dumps(
            {
                "url": "https://example.com",
                "timestamp": legacy_timestamp,
                "title": "Example Domain",
                "fs_version": "0.8.0",
                "archive_results": [],
            },
        ),
    )

    # Run update without filters - should import and migrate the legacy directory.
    update_process = subprocess.run(
        ["archivebox", "update"],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
        timeout=60,
    )
    assert update_process.returncode == 0, update_process.stderr

    conn = sqlite3.connect(str(tmp_path / "index.sqlite3"))
    c = conn.cursor()
    row = c.execute("SELECT url, fs_version FROM core_snapshot").fetchone()
    conn.commit()
    conn.close()

    assert row == ("https://example.com", "0.9.0")
    assert legacy_dir.is_symlink()

    migrated_dir = legacy_dir.resolve()
    assert migrated_dir.exists()
    assert (migrated_dir / "index.jsonl").exists()
    assert (migrated_dir / "singlefile.html").exists()


@pytest.mark.django_db
def test_reindex_snapshots_resets_existing_search_results_and_reruns_requested_plugins(monkeypatch):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.cli.archivebox_update import reindex_snapshots
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl
    import archivebox.cli.archivebox_extract as extract_mod

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
    )
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="search_backend_sqlite",
        hook_name="on_Snapshot__90_index_sqlite.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="old index hit",
        output_json={"indexed": True},
        output_files={"search.sqlite3": {"size": 123}},
        output_size=123,
    )

    captured: dict[str, object] = {}

    def fake_run_plugins(*, args, records, wait, emit_results, plugins=""):
        captured["args"] = args
        captured["records"] = records
        captured["wait"] = wait
        captured["emit_results"] = emit_results
        captured["plugins"] = plugins
        return 0

    monkeypatch.setattr(extract_mod, "run_plugins", fake_run_plugins)

    stats = reindex_snapshots(
        Snapshot.objects.filter(id=snapshot.id),
        search_plugins=["search_backend_sqlite"],
        batch_size=10,
    )

    result.refresh_from_db()

    assert stats["processed"] == 1
    assert stats["queued"] == 1
    assert stats["reindexed"] == 1
    assert result.status == ArchiveResult.StatusChoices.QUEUED
    assert result.output_str == ""
    assert result.output_json is None
    assert result.output_files == {}
    assert captured == {
        "args": (),
        "records": [{"type": "ArchiveResult", "snapshot_id": str(snapshot.id), "plugin": "search_backend_sqlite"}],
        "wait": True,
        "emit_results": False,
        "plugins": "",
    }


@pytest.mark.django_db
def test_build_filtered_snapshots_queryset_respects_resume_cutoff():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.cli.archivebox_update import _build_filtered_snapshots_queryset
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(
        urls="https://example.com\nhttps://example.org\nhttps://example.net",
        created_by_id=get_or_create_system_user_pk(),
    )
    base = timezone.make_aware(datetime(2026, 3, 23, 12, 0, 0))
    older = Snapshot.objects.create(
        url="https://example.net",
        crawl=crawl,
        bookmarked_at=base - timedelta(hours=2),
    )
    middle = Snapshot.objects.create(
        url="https://example.org",
        crawl=crawl,
        bookmarked_at=base - timedelta(hours=1),
    )
    newer = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        bookmarked_at=base,
    )

    snapshots = list(
        _build_filtered_snapshots_queryset(
            filter_patterns=(),
            filter_type="exact",
            before=None,
            after=None,
            resume=middle.timestamp,
        ).values_list("id", flat=True),
    )

    assert str(newer.id) not in {str(snapshot_id) for snapshot_id in snapshots}
    assert set(map(str, snapshots)) == {str(middle.id), str(older.id)}


@pytest.mark.django_db
def test_reconcile_with_index_json_tolerates_null_title(tmp_path):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        title="Example Domain",
        status=Snapshot.StatusChoices.SEALED,
    )
    output_dir = snapshot.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.json").write_text(
        json.dumps(
            {
                "url": snapshot.url,
                "timestamp": snapshot.timestamp,
                "title": None,
                "archive_results": [],
            },
        ),
    )

    snapshot.reconcile_with_index_json()
    snapshot.refresh_from_db()

    assert snapshot.title == "Example Domain"


@pytest.mark.django_db
def test_reindex_snapshots_batches_run_plugins(monkeypatch):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.cli.archivebox_update import reindex_snapshots
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    import archivebox.cli.archivebox_extract as extract_mod

    crawl = Crawl.objects.create(
        urls="https://example.com\nhttps://example.org",
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshots = [
        Snapshot.objects.create(url=f"https://example.com/{i}", crawl=crawl, status=Snapshot.StatusChoices.SEALED)
        for i in range(3)
    ]

    captured_batches: list[list[dict[str, str]]] = []

    def fake_run_plugins(*, args, records, wait, emit_results, plugins=""):
        captured_batches.append(list(records))
        return 0

    monkeypatch.setattr(extract_mod, "run_plugins", fake_run_plugins)

    stats = reindex_snapshots(
        Snapshot.objects.filter(id__in=[snapshot.id for snapshot in snapshots]),
        search_plugins=["search_backend_sqlite"],
        batch_size=2,
    )

    assert stats["processed"] == 3
    assert stats["queued"] == 3
    assert stats["reindexed"] == 3
    assert len(captured_batches) == 2
    assert len(captured_batches[0]) == 2
    assert len(captured_batches[1]) == 1


@pytest.mark.django_db
def test_process_filtered_snapshots_preserve_save_hooks_toggles_save_signals():
    from django.db.models.signals import post_save
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.cli.archivebox_update import process_filtered_snapshots
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
    )

    save_signals = {"count": 0}

    def handler(sender, **kwargs):
        save_signals["count"] += 1

    post_save.connect(handler, sender=Snapshot, weak=False)
    try:
        stats = process_filtered_snapshots(
            filter_patterns=[snapshot.url],
            filter_type="exact",
            before=None,
            after=None,
            resume=None,
            batch_size=1,
            preserve_save_hooks=False,
        )

        assert stats["queued"] == 1
        assert save_signals["count"] == 0

        save_signals["count"] = 0

        stats = process_filtered_snapshots(
            filter_patterns=[snapshot.url],
            filter_type="exact",
            before=None,
            after=None,
            resume=None,
            batch_size=1,
            preserve_save_hooks=True,
        )

        assert stats["queued"] == 1
        assert save_signals["count"] >= 1
    finally:
        post_save.disconnect(handler, sender=Snapshot)


@pytest.mark.django_db
def test_build_filtered_snapshots_queryset_respects_resume_cutoff_with_timestamp_order_mismatch():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.cli.archivebox_update import _build_filtered_snapshots_queryset
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(
        urls="https://example.com\nhttps://example.org\nhttps://example.net",
        created_by_id=get_or_create_system_user_pk(),
    )
    base = timezone.make_aware(datetime(2026, 3, 23, 12, 0, 0))
    older = Snapshot.objects.create(
        url="https://example.net",
        crawl=crawl,
        bookmarked_at=base - timedelta(hours=2),
        timestamp=str((base + timedelta(hours=3)).timestamp()),
    )
    middle = Snapshot.objects.create(
        url="https://example.org",
        crawl=crawl,
        bookmarked_at=base - timedelta(hours=1),
        timestamp=str((base - timedelta(hours=1)).timestamp()),
    )
    newer = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        bookmarked_at=base,
        timestamp=str((base + timedelta(hours=1)).timestamp()),
    )

    snapshots = list(
        _build_filtered_snapshots_queryset(
            filter_patterns=(),
            filter_type="exact",
            before=None,
            after=None,
            resume=middle.timestamp,
        ).values_list("id", flat=True),
    )

    assert set(map(str, snapshots)) == {str(middle.id), str(older.id)}
    assert str(newer.id) not in {str(snapshot_id) for snapshot_id in snapshots}


def test_move_tree_fast_falls_back_on_exdev(monkeypatch, tmp_path):
    from archivebox.cli.archivebox_update import _move_tree_fast

    src = tmp_path / "old"
    dst = tmp_path / "new"
    src.mkdir()
    (src / "file.txt").write_text("hello")

    def fake_rename(src_path, dst_path):
        raise OSError(errno.EXDEV, "Cross-device link")

    monkeypatch.setattr(os, "rename", fake_rename)

    succeeded = _move_tree_fast(src, dst)

    assert succeeded is False
    assert src.exists()
    assert not dst.exists()
