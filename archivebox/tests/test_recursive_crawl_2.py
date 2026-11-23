#!/usr/bin/env python3
"""Integration tests for recursive crawling functionality."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

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


def read_pressure_fixture(name):
    stderr = (Path(__file__).parent / "fixtures" / name).read_text()
    # The recorded runs predate the worker modules' namespace change.
    return stderr.replace(" archivebox.services.", " archivebox.workers.")


@pytest.mark.parametrize("active_pressure", [False, True])
@pytest.mark.parametrize("memory_observation", [False, True])
@pytest.mark.parametrize("pressure_reason", ["io stalls", "cpu quota throttling"])
@pytest.mark.parametrize("invalid", [None, "absent", "stale", "other-crawl", "parallel", "missing-decision", "unmeasured", "not-denied"])
def test_serialized_recovery_requires_matching_observed_evidence(invalid, active_pressure, pressure_reason, memory_observation):
    # Exact stderr excerpt and first-hook timestamps from the real hosted run.
    stderr = read_pressure_fixture("admission-pressure-recovery.txt")
    stderr = stderr.replace("io stalls", pressure_reason)
    if memory_observation:
        stderr = stderr.replace(" pressure=none", " active_memory=None pressure=none")
    if active_pressure:
        # Same strict evidence contract for the active-pressure branch, whose
        # native cgroup regression proves it can deny without the idle warning.
        stderr = re.sub(
            r"WARNING archivebox.workers.runner (Capture admission deferred[^\n]+)",
            r"WARNING archivebox.workers.resource_admission \1 (active=1 slots=0 adaptive=1)",
            stderr,
        )
    crawl_id = "06ad71db64ea72bb80002740d5283a00"
    starts = [datetime.fromisoformat(value) for value in ("2026-10-20T07:52:43.845871+00:00", "2026-10-20T07:52:46.034821+00:00")]
    if invalid == "absent":
        stderr = "\n".join(line for line in stderr.splitlines() if "WARNING" not in line)
    elif invalid == "stale":
        stderr = stderr.replace("07:52:41", "07:52:01")
    elif invalid == "other-crawl":
        crawl_id = "unrelated-crawl"
    elif invalid == "parallel":
        stderr = stderr.replace("adaptive=1 active=0 slots=1", "adaptive=2 active=0 slots=2")
    elif invalid == "missing-decision":
        stderr = "\n".join(line for line in stderr.splitlines() if "07:52:45" not in line)
    elif invalid == "unmeasured":
        stderr = re.sub(r"observed_cost=\d+", "observed_cost=0", stderr)
    elif invalid == "not-denied":
        stderr = stderr.replace("Capture admission deferred", "Capture admission allowed").replace("slots=0", "slots=1")
    if invalid:
        with pytest.raises(AssertionError):
            assert_serialized_pressure_recovery(stderr, crawl_id, starts)
    else:
        assert_serialized_pressure_recovery(stderr, crawl_id, starts)


@pytest.mark.parametrize("invalid", [None, "early-parallel", "late-decision", "no-fresh-pressure", "overpromised"])
def test_serialized_recovery_allows_spare_slots_for_final_snapshot(invalid):
    # The hosted rc368 run was genuinely serialized after recent I/O stalls.
    # Use its real admission timeline. The first replayed start is the lower
    # boundary of the second snapshot's decision; the final start is exact.
    stderr = read_pressure_fixture("admission-pressure-final-snapshot.txt")
    first = datetime.fromisoformat("2026-11-20T13:46:16+00:00")
    final = datetime.fromisoformat("2026-11-20T13:46:35.335158+00:00")
    if invalid == "early-parallel":
        stderr = stderr.replace("adaptive=1 active=0 slots=1", "adaptive=2 active=0 slots=2")
    elif invalid == "late-decision":
        stderr = stderr.replace("13:46:35", "13:46:36")
    elif invalid == "no-fresh-pressure":
        stderr = "\n".join(line for line in stderr.splitlines() if "13:46:33" not in line)
    elif invalid == "overpromised":
        stderr = stderr.replace("17048039424", "205127884")
    crawl_id = "00000000000000000000000000000001"
    if invalid:
        with pytest.raises(AssertionError):
            assert_serialized_pressure_recovery(stderr, crawl_id, [first, final])
    else:
        assert_serialized_pressure_recovery(stderr, crawl_id, [first, final])


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


def test_crawl_snapshot_has_parent_snapshot_field(tmp_path, initialized_archive):
    """Test that Snapshot model has parent_snapshot field."""

    column_names = {field.column for field in Snapshot._meta.local_fields}

    assert "parent_snapshot_id" in column_names, f"Snapshot table should have parent_snapshot_id column. Columns: {column_names}"
