"""Cancellation of untouched queue rows must not depend on archive storage."""

import sys

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl


@pytest.mark.django_db
def test_cancel_never_started_snapshot_does_not_scan_archive_storage(admin_user):
    crawl = Crawl.objects.create(urls="https://archivebox.io/tests/cancel", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    output_dir = snapshot.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    scans = []
    observing = True

    def observe(event, args):
        if observing and event == "os.scandir" and str(args[0]).rstrip("/") == str(output_dir):
            scans.append(args[0])

    sys.addaudithook(observe)
    try:
        crawl.cancel()
        assert snapshot.reconcile_parent_lifecycle() is True
        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert snapshot.downloaded_at is None
        assert not snapshot.archiveresult_set.exists()
    finally:
        observing = False
    assert scans == []
    assert list(output_dir.iterdir()) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status,has_result,output_size",
    [("started", False, 0), ("paused", False, 0), ("queued", True, 0), ("queued", False, 14)],
)
def test_cancel_preserves_capture_cleanup_for_started_or_projected_rows(admin_user, status, has_result, output_size):
    crawl = Crawl.objects.create(urls="https://archivebox.io/tests/cancel-partial", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, status=status, output_size=output_size)
    if has_result:
        ArchiveResult.objects.create(snapshot=snapshot, plugin="title", hook_name="on_Snapshot__10_title")
    output_dir = snapshot.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    pid_file = output_dir / "finished.pid"
    pid_file.write_text("0")
    partial = output_dir / "partial.txt"
    partial.write_text("captured bytes")

    snapshot.cancel()

    snapshot.refresh_from_db()
    assert snapshot.status == Snapshot.StatusChoices.SEALED
    assert not pid_file.exists()
    assert partial.read_text() == "captured bytes"
