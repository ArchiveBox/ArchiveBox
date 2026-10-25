"""Crawl completion is a downloader fact, never inferred during runner exit."""

import asyncio

import pytest

from abx_dl.events import CrawlCleanupEvent, CrawlCompletedEvent
from archivebox.base_models.models import get_or_create_system_user_pk
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.services.runner import CrawlRunner

pytestmark = pytest.mark.django_db(transaction=True)


def test_failed_crawl_cleanup_seals_with_failure_after_snapshots_settle(tmp_path, cached_abxpkg_lib_dir):
    crawl = Crawl.objects.create(
        urls="https://example.com/cleanup-boundary",
        config={"PLUGINS": "hashes"},
        created_by_id=get_or_create_system_user_pk(),
    )
    runner = CrawlRunner(crawl, show_progress=False)
    completed = []
    output = tmp_path / "cleanup.jsonl"
    output.mkdir()

    async def persist_cleanup(event: CrawlCleanupEvent):
        # A real completion-file consumer fails on a real filesystem collision.
        # The real error must survive cleanup and terminal projection; ending
        # the execution is not a claim that its manifest write succeeded.
        await asyncio.to_thread(output.write_text, event.model_dump_json() + "\n")

    runner.bus.on(CrawlCleanupEvent, persist_cleanup)
    runner.bus.on(CrawlCompletedEvent, lambda event: completed.append(event))
    with pytest.raises(Exception, match="cleanup.jsonl"):
        asyncio.run(runner.run())

    assert len(completed) == 1
    assert "cleanup.jsonl" in completed[0].error
    snapshot = Snapshot.objects.get(crawl=crawl)
    assert snapshot.status == Snapshot.StatusChoices.SEALED
    assert snapshot.archiveresult_set.get(plugin="hashes").status == ArchiveResult.StatusChoices.SUCCEEDED
    assert (snapshot.output_dir / "hashes/hashes.json").is_file()
    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at is None
    assert "cleanup.jsonl" in crawl.notes
    assert output.is_dir()
