#!/usr/bin/env python3
"""Integration tests for recursive crawling functionality."""

import os
import re
from datetime import datetime, timezone

import pytest

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process
from archivebox.tests.conftest import run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def assert_serialized_pressure_recovery(stderr, crawl_id, starts):
    """Require a distinct measured recovery for each serial start."""
    pressure_reason = r"(?:(?:cpu|memory|io) stalls|cpu quota throttling)"
    pressure_times = [
        datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        for source, suffix in (
            ("runner", ""),
            ("resource_admission", r" \(active=\d+ slots=0 adaptive=\d+\)"),
        )
        for stamp in re.findall(
            rf"\[([^]\n]+)\] WARNING archivebox.workers.{source} Capture admission deferred for crawl {re.escape(crawl_id)}: "
            rf"{pressure_reason}(?:, {pressure_reason})*{suffix}$",
            stderr,
            re.M,
        )
    ]
    decisions = [
        (datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc), int(adaptive), int(active), int(slots), int(cost), int(available))
        for stamp, adaptive, active, slots, cost, available in re.findall(
            r"\[([^]\n]+)\] INFO archivebox.workers.resource_admission Snapshot admission decision: "
            r"configured=3 adaptive=(\d+) active=(\d+) slots=(\d+) observed_cost=(\d+) available=(\d+)(?: active_memory=(?:None|\d+))? pressure=none$",
            stderr,
            re.M,
        )
    ]
    assert starts and pressure_times and decisions, stderr
    used_decisions = set()
    for index, started in enumerate(sorted(starts)):
        matching = [decision for decision in decisions if decision[0] <= started]
        assert matching, (started, stderr)
        decision, adaptive, active, slots, cost, available = matching[-1]
        assert active == 0 and 1 <= slots <= adaptive <= 3 and cost > 0 and available >= slots * cost, (started, stderr)
        assert decision not in used_decisions, (started, stderr)
        used_decisions.add(decision)
        # The direct runner batches at most the remaining snapshot IDs. More
        # than one slot fails to explain serialization while two are pending,
        # but cannot launch a parallel capture when only the final ID remains.
        remaining = len(starts) - index
        assert remaining == 1 or (adaptive, slots) == (1, 1), (started, stderr)
        assert any(pressure <= decision and 0 <= (started - pressure).total_seconds() < 10 for pressure in pressure_times), (
            started,
            stderr,
        )


@pytest.mark.timeout(600)
def test_direct_url_crawl_measures_first_snapshot_before_parallel_admission(
    initialized_archive,
    recursive_test_site,
    cached_abxpkg_lib_dir,
):
    """A real three-URL capture must not launch all Chrome hook trees at once."""
    urls = [recursive_test_site["root_url"], *recursive_test_site["child_urls"][:2]]
    env = os.environ.copy()
    env.update(
        {
            "TZ": "UTC",
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
            "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*",
            "ABXPKG_LIB_DIR": str(cached_abxpkg_lib_dir),
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
    measurements = [
        datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        for stamp in re.findall(
            r"\[([^]\n]+)\] INFO archivebox.workers.runner Snapshot admission: concurrency limit=3, observed memory cost=[1-9]\d* bytes",
            result.stderr,
        )
    ]
    assert measurements and min(measurements) <= min(later_starts), result.stderr
    later_intervals = [
        (snapshot_id, started, ended) for snapshot_id, started, ended in hook_intervals if snapshot_id != first_id and started and ended
    ]
    overlapping = any(
        left_id != right_id and left_start < right_end and right_start < left_end
        for index, (left_id, left_start, left_end) in enumerate(later_intervals)
        for right_id, right_start, right_end in later_intervals[index + 1 :]
    )
    if not overlapping:
        # Shared CI can legitimately recover at one slot while these tiny
        # captures finish. Unexplained serialization must still fail. The full
        # depth-two crawl separately requires actual cross-snapshot overlap.
        starts = [min(start for sid, start, _end in later_intervals if sid == snapshot.id) for snapshot in snapshots[1:]]
        assert_serialized_pressure_recovery(result.stderr, str(crawl.id), starts)
