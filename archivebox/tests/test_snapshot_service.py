import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from django.db import close_old_connections

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.tests.conftest import run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db
from .conftest import (
    cli_env,
    get_free_port,
    init_archive,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _snapshot_state(cwd: Path, url: str) -> dict[str, object]:
    with use_archivebox_db(cwd):
        snapshot = Snapshot.objects.select_related("crawl", "crawl__created_by").get(url=url)
        snapshot_dir = Path(snapshot.output_dir)
        crawl_dir = Path(snapshot.crawl.output_dir)
        crawl_link = crawl_dir / "snapshots" / Snapshot.extract_domain_from_url(snapshot.url) / str(snapshot.id)
        results = list(
            ArchiveResult.objects.filter(snapshot=snapshot)
            .order_by("plugin", "hook_name")
            .values("plugin", "hook_name", "status", "output_files", "output_size"),
        )
        return {
            "id": str(snapshot.id),
            "crawl_id": str(snapshot.crawl_id),
            "status": snapshot.status,
            "retry_at": snapshot.retry_at,
            "downloaded_at": snapshot.downloaded_at,
            "output_size": snapshot.output_size,
            "snapshot_dir": snapshot_dir,
            "crawl_dir": crawl_dir,
            "crawl_link": crawl_link,
            "results": results,
        }


def test_snapshot_completion_preserves_retry_scheduled_during_active_run(tmp_path, admin_user):
    from datetime import timedelta

    from django.utils import timezone

    from archivebox.crawls.models import Crawl
    from archivebox.services.snapshot_service import finalize_completed_snapshot

    crawl = Crawl.objects.create(urls="https://example.com/retry-race", created_by=admin_user)
    owned_retry_at = timezone.now() + timedelta(minutes=10)
    snapshot = Snapshot.objects.create(
        url="https://example.com/retry-race",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
        retry_at=owned_retry_at,
        config={"RETRY_PLUGINS": ["title"]},
    )

    snapshot.schedule_plugin_run(["title"])
    finalize_completed_snapshot(
        str(snapshot.id),
        owned_retry_at=owned_retry_at,
        was_sealed=False,
        consumed_retry_plugins=["title"],
        output_dir=tmp_path,
    )

    snapshot.refresh_from_db()
    assert snapshot.status == Snapshot.StatusChoices.QUEUED
    assert snapshot.retry_at is not None
    assert snapshot.retry_at < owned_retry_at
    assert snapshot.config["RETRY_PLUGINS"] == ["title"]


def test_concurrent_plugin_scheduling_durably_merges_every_request(admin_user):
    from archivebox.crawls.models import Crawl
    from django.db import connection

    if connection.vendor != "sqlite":
        pytest.skip("exercises SQLite concurrent-writer scheduling")

    crawl = Crawl.objects.create(urls="https://example.com/plugin-race", created_by=admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/plugin-race", crawl=crawl)
    plugins = ["title", "wget", "screenshot", "pdf"]

    def schedule(plugin: str) -> bool:
        close_old_connections()
        try:
            return Snapshot.objects.get(pk=snapshot.pk).schedule_plugin_run([plugin])
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=len(plugins)) as pool:
        results = list(pool.map(schedule, plugins))

    snapshot.refresh_from_db()
    assert results == [True] * len(plugins)
    assert snapshot.config["RETRY_PLUGINS"] == sorted(plugins)


def test_snapshot_keyset_iterator_reads_more_than_eight_pages(admin_user):
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(urls="https://example.com/pages", created_by=admin_user)
    snapshots = [Snapshot.objects.create(url=f"https://example.com/pages/{idx}", crawl=crawl) for idx in range(10)]

    yielded_ids = [snapshot.id for snapshot in crawl.snapshot_set.order_by("id").paged_iterator(chunk_size=1)]

    assert yielded_ids == sorted(snapshot.id for snapshot in snapshots)


def test_snapshot_merge_consolidates_only_exact_hook_identity(admin_user):
    from archivebox.crawls.models import Crawl

    keeper_crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    duplicate_crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    keeper = Snapshot.objects.create(url="https://example.com", crawl=keeper_crawl)
    duplicate = Snapshot.objects.create(url="https://example.com", crawl=duplicate_crawl)
    ArchiveResult.objects.create(
        snapshot=keeper,
        plugin="archivewebpage",
        hook_name="on_Snapshot__65_archivewebpage_stop",
        status=ArchiveResult.StatusChoices.NORESULTS,
        output_files={"older.wacz": {"size": 5}},
        output_size=5,
    )
    ArchiveResult.objects.create(
        snapshot=duplicate,
        plugin="archivewebpage",
        hook_name="on_Snapshot__65_archivewebpage_stop",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="archivewebpage.wacz",
        output_files={"archivewebpage.wacz": {"size": 7}},
        output_size=7,
    )
    ArchiveResult.objects.create(
        snapshot=duplicate,
        plugin="archivewebpage",
        hook_name="on_Snapshot__16_archivewebpage_start",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="recording started",
    )

    Snapshot._merge_snapshots([keeper, duplicate])

    assert not Snapshot.objects.filter(pk=duplicate.pk).exists()
    results = ArchiveResult.objects.filter(snapshot=keeper, plugin="archivewebpage")
    assert results.count() == 2
    stop_result = results.get(hook_name="on_Snapshot__65_archivewebpage_stop")
    assert stop_result.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert stop_result.output_str == "archivewebpage.wacz"
    assert set(stop_result.output_files) == {"older.wacz", "archivewebpage.wacz"}
    assert results.filter(hook_name="on_Snapshot__16_archivewebpage_start").exists()


@pytest.mark.timeout(180)
def test_snapshot_service_cli_add_seals_snapshot_and_writes_indexes(tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(port=port, server=True, PLUGINS="wget", SAVE_WGET="True")
    _cmd_result = run_archivebox_cmd(
        ["add", "--depth=0", "--plugins=wget", recursive_test_site["root_url"]],
        cwd=tmp_path,
        env=env,
        timeout=180,
    )
    stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert code == 0, f"archivebox add failed with code {code}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"

    state = _snapshot_state(tmp_path, recursive_test_site["root_url"])
    snapshot_dir = state["snapshot_dir"]
    crawl_link = state["crawl_link"]
    assert isinstance(snapshot_dir, Path)
    assert isinstance(crawl_link, Path)

    assert state["status"] == Snapshot.StatusChoices.SEALED
    assert state["retry_at"] is None
    assert state["downloaded_at"] is not None
    assert snapshot_dir.is_dir()
    assert crawl_link.is_symlink()
    assert crawl_link.resolve() == snapshot_dir.resolve()

    index_jsonl = snapshot_dir / "index.jsonl"
    assert index_jsonl.is_file()

    records = [json.loads(line) for line in index_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records[0]["type"] == "Snapshot"
    assert records[0]["id"] == state["id"]
    assert any(record.get("type") == "ArchiveResult" and record.get("plugin") == "wget" for record in records)

    wget_files = [path for path in (snapshot_dir / "wget").rglob("*") if path.is_file()]
    assert wget_files
    assert any("Root" in path.read_text(encoding="utf-8", errors="ignore") for path in wget_files if path.suffix in (".html", ".txt"))
    assert any(result["plugin"] == "wget" and result["status"] == ArchiveResult.StatusChoices.SUCCEEDED for result in state["results"])
