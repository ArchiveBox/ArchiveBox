#!/usr/bin/env python3
"""CLI-specific tests for archivebox schedule."""

from archivebox.tests.conftest import run_archivebox_cmd

import pytest

from archivebox.crawls.models import Crawl, CrawlSchedule
from archivebox.tests.test_orm_helpers import use_archivebox_db
from .conftest import (
    cli_env,
    get_counts,
    get_free_port,
    init_archive,
    make_latest_schedule_due,
    start_archivebox_server,
    stop_server,
    get_http_response,
    wait_for_snapshot_capture,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_schedule_run_all_enqueues_scheduled_crawl(initialized_archive):

    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["schedule", "--every=daily", "--depth=0", "https://example.com"],
        check=True,
    )

    result = run_archivebox_cmd(
        ["schedule", "--run-all"],
        env=env,
    )

    assert result.returncode == 0
    assert "Enqueued 1 scheduled crawl" in result.stdout

    with use_archivebox_db(initialized_archive):
        crawl_count = Crawl.objects.count()
        queued_count = Crawl.objects.filter(status="queued").count()

    assert crawl_count >= 2
    assert queued_count >= 1


def test_schedule_without_import_path_creates_maintenance_schedule(initialized_archive):

    result = run_archivebox_cmd(
        ["schedule", "--every=day"],
    )

    assert result.returncode == 0
    assert "Created scheduled maintenance update" in result.stdout

    with use_archivebox_db(initialized_archive):
        schedule_row = CrawlSchedule.objects.select_related("template").get()

    assert schedule_row.kind == "update"
    assert schedule_row.template.urls == ""
    assert schedule_row.template.status == "sealed"


def test_schedule_creates_enabled_db_schedule(initialized_archive):

    result = run_archivebox_cmd(
        ["schedule", "--every=daily", "--depth=1", "https://example.com/feed.xml"],
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        schedule_row = CrawlSchedule.objects.order_by("-created_at").values_list("schedule", "is_enabled", "label").first()
        crawl = Crawl.objects.order_by("-created_at").first()

    assert schedule_row == ("daily", True, "Scheduled import: https://example.com/feed.xml")
    assert crawl is not None
    assert crawl.urls == "https://example.com/feed.xml"
    assert crawl.status == "sealed"
    assert crawl.max_depth == 1


def test_schedule_show_lists_enabled_schedules(initialized_archive):

    run_archivebox_cmd(
        ["schedule", "--every=weekly", "https://example.com/feed.xml"],
        check=True,
    )

    result = run_archivebox_cmd(
        ["schedule", "--show"],
    )

    assert result.returncode == 0
    assert "Active scheduled crawls" in result.stdout
    assert "https://example.com/feed.xml" in result.stdout
    assert "weekly" in result.stdout


def test_schedule_clear_disables_existing_schedules(initialized_archive):

    run_archivebox_cmd(
        ["schedule", "--every=daily", "https://example.com/feed.xml"],
        check=True,
    )

    result = run_archivebox_cmd(
        ["schedule", "--clear"],
    )

    assert result.returncode == 0
    assert "Disabled 1 scheduled crawl" in result.stdout

    with use_archivebox_db(initialized_archive):
        disabled_count = CrawlSchedule.objects.filter(is_enabled=False).count()
        enabled_count = CrawlSchedule.objects.filter(is_enabled=True).count()

    assert disabled_count == 1
    assert enabled_count == 0


def test_schedule_every_requires_valid_period(initialized_archive):

    result = run_archivebox_cmd(
        ["schedule", "--every=invalid_period", "https://example.com/feed.xml"],
    )

    assert result.returncode != 0
    assert "Invalid schedule" in result.stderr or "Invalid schedule" in result.stdout


def test_schedule_help_lists_schedule_options(initialized_archive):

    result = run_archivebox_cmd(
        ["schedule", "--help"],
    )

    assert result.returncode == 0
    assert "--every" in result.stdout
    assert "--show" in result.stdout
    assert "--clear" in result.stdout
    assert "--run-all" in result.stdout


@pytest.mark.timeout(180)
def test_schedule_due_crawl_runs_over_server_and_saves_real_content(tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(port=port, server=True)

    schedule_result = run_archivebox_cmd(
        ["schedule", "--every=daily", "--depth=0", recursive_test_site["root_url"]],
        cwd=tmp_path,
        env=env,
        timeout=60,
    )
    assert schedule_result.returncode == 0, schedule_result.stderr
    assert "Created scheduled crawl" in schedule_result.stdout

    make_latest_schedule_due(tmp_path)

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        get_http_response(port, host=f"web.archivebox.localhost:{port}")
        captured_text = wait_for_snapshot_capture(tmp_path, recursive_test_site["root_url"], timeout=180)
        assert "Root" in captured_text
        assert "About" in captured_text
    finally:
        stop_server(tmp_path)


@pytest.mark.timeout(180)
def test_add_remains_one_shot_when_schedule_is_due(tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(port=port, server=True)
    scheduled_url = recursive_test_site["root_url"]
    one_shot_url = recursive_test_site["child_urls"][0]

    schedule_result = run_archivebox_cmd(
        ["schedule", "--every=daily", "--depth=0", scheduled_url],
        cwd=tmp_path,
        env=env,
        timeout=60,
    )
    assert schedule_result.returncode == 0, schedule_result.stderr

    make_latest_schedule_due(tmp_path)

    add_result = run_archivebox_cmd(
        ["add", "--depth=0", "--plugins=wget", one_shot_url],
        cwd=tmp_path,
        env=env,
        timeout=120,
    )
    assert add_result.returncode == 0, add_result.stderr
    captured_text = wait_for_snapshot_capture(tmp_path, one_shot_url, timeout=120)
    assert "Deep About" in captured_text or "About" in captured_text

    scheduled_snapshots, one_shot_snapshots, scheduled_crawls = get_counts(tmp_path, scheduled_url, one_shot_url)
    assert one_shot_snapshots >= 1
    assert scheduled_snapshots == 0
    assert scheduled_crawls == 1  # template only, no materialized scheduled run
