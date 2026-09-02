import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from archivebox.tests.conftest import cli_env, run_archivebox_cmd

import pytest
from django.utils import timezone

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.tests.migrations_helpers import filesystem_manifest
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def test_update_imports_orphaned_snapshots(tmp_path, initialized_archive):
    """Test that archivebox update imports real legacy archive directories."""
    env = cli_env(disable_extractors=True)
    legacy_timestamp = "1710000000"
    legacy_dir = tmp_path / "archive" / legacy_timestamp
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "singlefile.html").write_text("<html>example</html>")
    (legacy_dir / "index.jsonl").write_text('{"type":"Process","id":"incomplete"}\n')
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

    # Run the migration phase only; default update also runs queued crawl work.
    update_process = run_archivebox_cmd(
        ["update", "--migrate-only"],
        env=env,
        timeout=60,
    )
    assert update_process.returncode == 0, update_process.stderr

    with use_archivebox_db(tmp_path):
        migrated_snapshot = Snapshot.objects.get()
        row = (migrated_snapshot.url, migrated_snapshot.fs_version)
        migrated_dir = Path(migrated_snapshot.output_dir)

    assert row == ("https://example.com", Snapshot._fs_current_version())
    assert not legacy_dir.exists()
    assert migrated_dir.exists()
    assert '{"type":"Process","id":"incomplete"}\n' in (migrated_dir / "index.jsonl").read_text()
    assert (migrated_dir / "singlefile.html").exists()


@pytest.mark.parametrize("source_version", tuple(Snapshot._FS_VERSION_MIGRATION_PATHS))
def test_update_migrates_every_declared_filesystem_version(tmp_path, initialized_archive, source_version):
    """Every declared hop must complete through the public maintenance command."""
    env = cli_env(disable_extractors=True)
    url = f"https://example.com/fs-{source_version}"
    legacy_layout = source_version.startswith(("0.7.", "0.8."))
    add_process = run_archivebox_cmd(["add", url], env=env, timeout=90)
    assert add_process.returncode == 0, add_process.stderr
    with use_archivebox_db(tmp_path):
        snapshot = Snapshot.objects.get(url=url)
        destination = snapshot.output_dir
        Snapshot.objects.filter(pk=snapshot.pk).update(
            fs_version=source_version,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=None,
        )
        snapshot.refresh_from_db()
        source_dir = tmp_path / "archive" / snapshot.timestamp if legacy_layout else destination
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="singlefile",
            hook_name="on_Snapshot__singlefile",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )

    if legacy_layout:
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "index.jsonl").unlink(missing_ok=True)
        (source_dir / "index.json").write_text(
            json.dumps(
                {
                    "url": url,
                    "timestamp": snapshot.timestamp,
                    "title": f"Filesystem {source_version}",
                    "fs_version": source_version,
                    "status": "queued",
                    "archive_results": [],
                },
            ),
        )
    if legacy_layout:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "existing-user-output.bin").write_bytes(b"preserve interrupted migration output")

    (source_dir / "unknown" / "empty").mkdir(parents=True, exist_ok=True)
    (source_dir / "unknown" / "payload.bin").write_bytes(b"filesystem migration payload\x00\xff")
    (source_dir / "unknown" / "payload-link").symlink_to("payload.bin")
    (source_dir / "singlefile").mkdir(exist_ok=True)
    (source_dir / "singlefile" / "singlefile.html").write_text("<html>preserved output</html>")
    original_tree = filesystem_manifest(source_dir)
    original_tree.pop("index.jsonl", None)

    update_process = run_archivebox_cmd(["update", "--migrate-only"], env=env, timeout=90)
    assert update_process.returncode == 0, f"Initial update failed: {update_process.stderr}"

    with use_archivebox_db(tmp_path):
        snapshot = Snapshot.objects.get(url=url)
        assert snapshot.fs_version == Snapshot._fs_current_version()
        migrated_dir = snapshot.output_dir.resolve()
        migrated_tree = filesystem_manifest(migrated_dir)
        assert snapshot.status == Snapshot.StatusChoices.QUEUED
        assert snapshot.retry_at is not None
        result.refresh_from_db()
        # Migration projects filesystem facts without changing result lifecycle.
        assert "singlefile.html" in result.output_files
        assert result.output_size > 0
        if legacy_layout:
            assert (migrated_dir / "existing-user-output.bin").read_bytes() == b"preserve interrupted migration output"

    assert {path: migrated_tree.get(path) for path in original_tree} == original_tree
    if legacy_layout:
        assert not source_dir.exists()

    update_process = run_archivebox_cmd(["update", "--migrate-only"], env=env, timeout=90)
    assert update_process.returncode == 0, f"Idempotency update failed: {update_process.stderr}"
    with use_archivebox_db(tmp_path):
        snapshot.refresh_from_db()
        assert snapshot.fs_version == Snapshot._fs_current_version()
        assert snapshot.retry_at is not None
        assert filesystem_manifest(snapshot.output_dir.resolve()) == migrated_tree


@pytest.mark.django_db(transaction=True)
def test_reindex_snapshots_runs_only_missing_sealed_search_indexes():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.cli.archivebox_update import reindex_snapshots
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(
        urls="https://example.com\nhttps://example.org",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.SEALED,
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
    )
    paused_snapshot = Snapshot.objects.create(
        url="https://example.com/paused",
        crawl=crawl,
        status=Snapshot.StatusChoices.PAUSED,
    )
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="search_backend_sqlite",
        hook_name="on_Snapshot__90_index_sqlite",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="old index hit",
        output_json={"indexed": True},
        output_files={"search.sqlite3": {"size": 123}},
        output_size=123,
    )
    output_dir = snapshot.output_dir
    (output_dir / "title").mkdir(parents=True, exist_ok=True)
    (output_dir / "title" / "title.txt").write_text("Example Domain")
    (output_dir / "dom").mkdir(parents=True, exist_ok=True)
    (output_dir / "dom" / "output.html").write_text("<html><body>Example searchable text</body></html>")
    missing_snapshot = Snapshot.objects.create(
        url="https://example.org",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
    )
    missing_output_dir = missing_snapshot.output_dir
    (missing_output_dir / "title").mkdir(parents=True, exist_ok=True)
    (missing_output_dir / "title" / "title.txt").write_text("Missing Search Index")

    original_engine = os.environ.get("SEARCH_BACKEND_ENGINE")
    os.environ["SEARCH_BACKEND_ENGINE"] = "sqlite"
    try:
        stats = reindex_snapshots(
            Snapshot.objects.filter(id__in=(snapshot.id, missing_snapshot.id, paused_snapshot.id)).select_related("crawl"),
            search_plugins=["search_backend_sqlite"],
            batch_size=10,
        )
    finally:
        if original_engine is None:
            os.environ.pop("SEARCH_BACKEND_ENGINE", None)
        else:
            os.environ["SEARCH_BACKEND_ENGINE"] = original_engine

    result.refresh_from_db()

    snapshot.refresh_from_db()
    missing_snapshot.refresh_from_db()
    assert stats["processed"] == 1
    assert stats["requested"] == 1
    assert stats["queued"] == 0
    assert stats["reindexed"] == 1
    assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert result.output_str == "old index hit"
    assert result.output_json == {"indexed": True}
    assert snapshot.status == Snapshot.StatusChoices.SEALED
    assert missing_snapshot.status == Snapshot.StatusChoices.SEALED
    assert missing_snapshot.archiveresult_set.filter(
        plugin="search_backend_sqlite",
        status__in=[ArchiveResult.StatusChoices.SUCCEEDED, ArchiveResult.StatusChoices.NORESULTS],
    ).exists()
    assert not paused_snapshot.archiveresult_set.exists()


@pytest.mark.django_db(transaction=True)
def test_update_schedule_backfills_missing_search_index_without_reopening_snapshot():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl, CrawlSchedule

    user_id = get_or_create_system_user_pk()
    template = Crawl.objects.create(
        urls="",
        created_by_id=user_id,
        status=Crawl.StatusChoices.SEALED,
    )
    schedule = CrawlSchedule.objects.create(
        template=template,
        schedule="daily",
        config={"SCHEDULE_KIND": "update"},
        created_by_id=user_id,
    )
    crawl = Crawl.objects.create(
        urls="https://example.com/scheduled-search",
        created_by_id=user_id,
        status=Crawl.StatusChoices.SEALED,
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com/scheduled-search",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        fs_version=Snapshot._fs_current_version(),
    )
    stale_snapshot = Snapshot.objects.create(
        url="https://example.com/stale-scheduled-search",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        fs_version=next(iter(Snapshot._FS_VERSION_MIGRATION_PATHS)),
        retry_at=None,
    )
    (snapshot.output_dir / "title").mkdir(parents=True, exist_ok=True)
    (snapshot.output_dir / "title" / "title.txt").write_text("Scheduled Search Index")

    original_engine = os.environ.get("SEARCH_BACKEND_ENGINE")
    os.environ["SEARCH_BACKEND_ENGINE"] = "sqlite"
    try:
        assert schedule.dispatch() is None
        first_modified_at = schedule.modified_at
        assert schedule.dispatch() is None
    finally:
        if original_engine is None:
            os.environ.pop("SEARCH_BACKEND_ENGINE", None)
        else:
            os.environ["SEARCH_BACKEND_ENGINE"] = original_engine

    snapshot.refresh_from_db()
    stale_snapshot.refresh_from_db()
    assert snapshot.status == Snapshot.StatusChoices.SEALED
    assert (
        ArchiveResult.objects.filter(
            snapshot=snapshot,
            plugin="search_backend_sqlite",
            status__in=[ArchiveResult.StatusChoices.SUCCEEDED, ArchiveResult.StatusChoices.NORESULTS],
        ).count()
        == 1
    )
    assert not ArchiveResult.objects.filter(snapshot=snapshot, status=ArchiveResult.StatusChoices.QUEUED).exists()
    assert stale_snapshot.retry_at is not None
    assert not ArchiveResult.objects.filter(snapshot=stale_snapshot, plugin="search_backend_sqlite").exists()
    assert schedule.modified_at >= first_modified_at


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
def test_build_filtered_snapshots_queryset_accepts_list_style_filters():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.cli.archivebox_update import _build_filtered_snapshots_queryset
    from archivebox.core.models import Snapshot, Tag
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(
        urls="https://example.com\nhttps://example.org",
        created_by_id=get_or_create_system_user_pk(),
    )
    tagged = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        title="Example Domain",
        status=Snapshot.StatusChoices.SEALED,
    )
    Snapshot.objects.create(
        url="https://example.org",
        crawl=crawl,
        title="Other Example",
        status=Snapshot.StatusChoices.QUEUED,
    )
    tagged.tags.add(Tag.objects.create(name="keep"))

    snapshots = list(
        _build_filtered_snapshots_queryset(
            filter_patterns=(),
            filter_type="exact",
            status=Snapshot.StatusChoices.SEALED,
            url__icontains="example",
            tag="keep",
            crawl_id=str(crawl.id),
            limit=1,
            sort="url",
        ).values_list("id", flat=True),
    )

    assert snapshots == [tagged.id]


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
def test_reconcile_with_index_json_imports_legacy_archive_results_and_process(tmp_path):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import ArchiveResult, Snapshot
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
    output_dir = snapshot.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.json").write_text(
        json.dumps(
            {
                "url": snapshot.url,
                "timestamp": snapshot.timestamp,
                "title": "Example Domain",
                "archive_results": [
                    {
                        "plugin": "screenshot",
                        "status": "succeeded",
                        "output": "screenshot.png",
                        "output_files": {"screenshot.png": {"size": 3}},
                        "output_size": 3,
                        "start_ts": "2024-01-01T00:00:00+00:00",
                        "end_ts": "2024-01-01T00:00:01+00:00",
                        "cmd": ["screenshot", snapshot.url],
                        "pwd": str(output_dir / "screenshot"),
                    },
                ],
            },
        ),
    )

    snapshot.reconcile_with_index_json()

    result = ArchiveResult.objects.get(snapshot=snapshot, plugin="screenshot")
    assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert result.output_str == "screenshot.png"
    assert result.output_files == {"screenshot.png": {"extension": "png", "mimetype": "image/png", "size": 3}}
    assert result.process is not None
    assert result.cmd == ["screenshot", snapshot.url]
    assert result.pwd == str(output_dir / "screenshot")
    assert (output_dir / "index.json").exists()
    jsonl_text = (output_dir / "index.jsonl").read_text()
    assert '"type": "ArchiveResult"' in jsonl_text
    assert '"type": "Process"' in jsonl_text


@pytest.mark.django_db
def test_reconcile_with_index_json_merges_retried_archive_results(tmp_path):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import ArchiveResult, Snapshot
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
    output_dir = snapshot.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.json").write_text(
        json.dumps(
            {
                "url": snapshot.url,
                "timestamp": snapshot.timestamp,
                "title": "Example Domain",
                "archive_results": [
                    {
                        "plugin": "dom",
                        "hook_name": "on_Snapshot__12_dom.js",
                        "status": "failed",
                        "output": "first attempt failed",
                        "start_ts": "2024-01-01T00:00:00+00:00",
                        "end_ts": "2024-01-01T00:00:01+00:00",
                    },
                    {
                        "plugin": "dom",
                        "hook_name": "on_Snapshot__12_dom.js",
                        "status": "succeeded",
                        "output": "dom/output.html",
                        "output_files": {"output.html": {"size": 42}},
                        "output_size": 42,
                        "start_ts": "2024-01-01T00:01:00+00:00",
                        "end_ts": "2024-01-01T00:01:01+00:00",
                    },
                ],
            },
        ),
    )

    snapshot.reconcile_with_index_json()

    result = ArchiveResult.objects.get(snapshot=snapshot, plugin="dom", hook_name="on_Snapshot__12_dom.js")
    assert ArchiveResult.objects.filter(snapshot=snapshot, plugin="dom", hook_name="on_Snapshot__12_dom.js").count() == 1
    assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert result.output_str == "dom/output.html"
    assert result.output_size == 42


@pytest.mark.django_db
def test_reconcile_with_index_json_trusts_legacy_archive_results(tmp_path):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(
        urls="https://example.com/page",
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com/page",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
    )
    output_dir = snapshot.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "screenshot.png").write_bytes(b"png")
    (output_dir / "output.html").write_text("<html>root wget output</html>")
    (output_dir / "example.com").mkdir()
    (output_dir / "example.com" / "page.html").write_text("<html>mirror output</html>")
    (output_dir / "cdn.example.com").mkdir()
    (output_dir / "cdn.example.com" / "asset.js").write_text("console.log('asset')")
    (output_dir / "index.json").write_text(
        json.dumps(
            {
                "url": snapshot.url,
                "timestamp": snapshot.timestamp,
                "title": "Example Domain",
                "archive_results": [
                    {
                        "plugin": "screenshot",
                        "status": "succeded",
                        "output": "screenshot.png",
                        "start_ts": "2024-01-01T00:00:00+00:00",
                        "end_ts": "2024-01-01T00:00:01+00:00",
                    },
                    {
                        "plugin": "wget",
                        "status": "succeeded",
                        "output": "example.com/page.html",
                        "start_ts": "2024-01-01T00:00:02+00:00",
                        "end_ts": "2024-01-01T00:00:03+00:00",
                    },
                ],
            },
        ),
    )

    snapshot.reconcile_with_index_json()

    results = {result.plugin: result for result in ArchiveResult.objects.filter(snapshot=snapshot)}
    assert set(results) == {"screenshot", "wget"}
    assert results["screenshot"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert results["screenshot"].output_str == "screenshot.png"
    assert results["screenshot"].output_files == {}
    assert results["wget"].output_str == "example.com/page.html"
    assert results["wget"].output_files == {}
