#!/usr/bin/env python3
"""Integration tests for recursive crawling functionality."""

import os

import pytest

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process
from archivebox.tests.conftest import run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

from .test_recursive_crawl_1 import (
    pytestmark as pytestmark,
    run_add_until as run_add_until,
)


@pytest.mark.timeout(600)
def test_direct_url_crawl_measures_first_snapshot_before_parallel_admission(initialized_archive, recursive_test_site):
    """A real three-URL capture must not launch all Chrome hook trees at once."""
    urls = [recursive_test_site["root_url"], *recursive_test_site["child_urls"][:2]]
    env = os.environ.copy()
    env.update(
        {
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
            "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*",
            "ABXPKG_LIB_DIR": str(initialized_archive / "lib"),
            "CHROME_HEADLESS": "true",
            "CHROME_SANDBOX": "false",
            "CHROME_ISOLATION": "crawl",
            "CRAWL_MAX_CONCURRENT_SNAPSHOTS": "3",
            "TIMEOUT": "90",
        },
    )
    result = run_archivebox_cmd(
        ["add", "--parser=url_list", "--plugins=chrome,wget,screenshot", "--tag=measured-admission", *urls],
        cwd=initialized_archive,
        env=env,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get(tags_str="measured-admission")
        snapshots = list(Snapshot.objects.filter(crawl=crawl).order_by("created_at"))
        hook_intervals = list(
            Process.objects.filter(
                process_type=Process.TypeChoices.HOOK,
                archiveresult__snapshot__crawl=crawl,
            )
            .values_list("archiveresult__snapshot_id", "started_at", "ended_at")
            .distinct(),
        )

    assert len(snapshots) == 3
    assert all(snapshot.status == Snapshot.StatusChoices.SEALED and snapshot.downloaded_at for snapshot in snapshots)
    first_id = snapshots[0].id
    first_end = snapshots[0].downloaded_at
    later_starts = [started for snapshot_id, started, _ended in hook_intervals if snapshot_id != first_id and started]
    assert later_starts and first_end <= min(later_starts), hook_intervals
    later_intervals = [
        (snapshot_id, started, ended) for snapshot_id, started, ended in hook_intervals if snapshot_id != first_id and started and ended
    ]
    assert any(
        left_id != right_id and left_start < right_end and right_start < left_end
        for index, (left_id, left_start, left_end) in enumerate(later_intervals)
        for right_id, right_start, right_end in later_intervals[index + 1 :]
    ), later_intervals


def test_crawl_snapshot_has_parent_snapshot_field(tmp_path, initialized_archive):
    """Test that Snapshot model has parent_snapshot field."""

    column_names = {field.column for field in Snapshot._meta.local_fields}

    assert "parent_snapshot_id" in column_names, f"Snapshot table should have parent_snapshot_id column. Columns: {column_names}"
