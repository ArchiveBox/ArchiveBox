"""Scheduled crawl navigation uses native schedule and run records."""

from datetime import datetime, timedelta, timezone as utc_timezone
from time import perf_counter
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from archivebox.core.sidebar_schedules import schedule_add_actions, schedule_entries_page
from archivebox.crawls.models import Crawl, CrawlSchedule


pytestmark = pytest.mark.django_db
TICK = datetime(2026, 11, 24, 15, 40, tzinfo=utc_timezone.utc)


def _request(user, **query):
    request = RequestFactory().get("/admin/core/snapshot/", query)
    request.user = user
    return request


def _schedule(
    owner,
    *,
    label="",
    template_label="",
    urls="# Seed comment\nhttps://feed.example.net/archive/",
    frequency="daily",
    enabled=True,
    tick=TICK,
):
    template = Crawl.objects.create(
        created_by=owner,
        urls=urls,
        label=template_label,
        created_at=tick,
    )
    return CrawlSchedule.objects.create(
        created_by=owner,
        template=template,
        label=label,
        schedule=frequency,
        is_enabled=enabled,
        created_at=tick,
    )


def _page(request, *, term="", parent="", cursor=None, limit=2):
    return schedule_entries_page(request, term=term, parent=parent, cursor=cursor, limit=limit)


def test_schedule_sidebar_keysets_roots_and_runs_independently(admin_user):
    first = _schedule(
        admin_user,
        label="Reading feeds",
        urls=(
            "# Ignore https://comments.invalid/\n"
            "https://someone:password@FEED.example.net:8443/archive?a=secret\n"
            '{"url":"https://api.google.co.uk/feed?x=1"}\n'
            "http://feed.example.net/dedup\n"
            "https://github.io/\n"
        ),
    )
    same_timestamp = _schedule(admin_user, template_label="Reading feeds", frequency="0 0 * * 0", enabled=False)
    last = _schedule(admin_user, frequency="0 */6 * * *", tick=TICK - timedelta(days=1))
    request = _request(admin_user)

    roots, cursor = _page(request)
    assert [item["id"] for item in roots] == sorted([str(first.pk), str(same_timestamp.pk)], reverse=True)
    assert {item["name"] for item in roots} == {"feed.example.net,api.google.co.uk,github.io (daily)", "feed.example.net (weekly)"}
    assert all(item["scope"] == "crawl_schedule" and item["parent_id"] == "" and item["has_children"] for item in roots)
    tail, end = _page(request, cursor=cursor)
    assert [(item["id"], item["name"]) for item in tail] == [(str(last.pk), "feed.example.net (0 */6 * * *)")]
    assert end is None
    assert [item["id"] for item in _page(request, term="weekly")[0]] == [str(same_timestamp.pk)]
    assert [item["id"] for item in _page(request, term="feed.example")[0]] == [item["id"] for item in roots]
    assert [item["id"] for item in _page(request, term="feed.example", cursor=cursor)[0]] == [str(last.pk)]

    oldest = first.template
    newest = Crawl.objects.create(created_by=admin_user, schedule=first, label="Newer", created_at=TICK + timedelta(days=1))
    matching_ts = Crawl.objects.create(created_by=admin_user, schedule=first, label="Same minute", created_at=newest.created_at)
    Crawl.objects.create(created_by=admin_user, schedule=same_timestamp, label="Other schedule")
    Crawl.objects.create(created_by=admin_user, label="No schedule")
    with timezone.override(ZoneInfo("America/Los_Angeles")):
        runs, next_run = _page(request, parent=str(first.pk), term="Reading feeds")
        more, end_run = _page(request, parent=str(first.pk), cursor=next_run)
    assert [item["id"] for item in runs] == sorted([str(newest.pk), str(matching_ts.pk)], reverse=True)
    assert [item["name"] for item in runs] == ["2026-11-25 07:40", "2026-11-25 07:40"]
    assert all(item["scope"] == "crawl" and item["parent_id"] == str(first.pk) and not item["has_children"] for item in runs)
    assert [item["id"] for item in more] == [str(oldest.pk)]
    assert end_run is None
    assert runs[0]["actions"] == [{"label": "Edit", "url": reverse("admin:crawls_crawl_change", args=[runs[0]["id"]])}]


def test_schedule_sidebar_reveals_selected_run_without_replaying_prior_pages(admin_user):
    newest_root = _schedule(admin_user, label="New schedule", tick=TICK + timedelta(days=2))
    older_root = _schedule(admin_user, label="Older schedule", tick=TICK + timedelta(days=1))
    selected_root = _schedule(admin_user, label="Selected schedule")
    selected_run = selected_root.template
    newer = Crawl.objects.create(created_by=admin_user, schedule=selected_root, created_at=TICK + timedelta(seconds=2))
    intermediate = Crawl.objects.create(created_by=admin_user, schedule=selected_root, created_at=TICK + timedelta(seconds=1))
    request = _request(admin_user, crawl=str(selected_run.pk))

    roots, cursor = _page(request, limit=1)
    assert [(item["id"], item["expand"]) for item in roots] == [(str(newest_root.pk), False), (str(selected_root.pk), True)]
    later_roots, end = _page(request, cursor=cursor, limit=1)
    assert [item["id"] for item in later_roots] == [str(older_root.pk)]
    assert end is None

    runs, cursor = _page(request, parent=str(selected_root.pk), limit=1)
    assert [item["id"] for item in runs] == [str(newer.pk), str(selected_run.pk)]
    later_runs, end = _page(request, parent=str(selected_root.pk), cursor=cursor, limit=1)
    assert [item["id"] for item in later_runs] == [str(intermediate.pk)]
    assert end is None

    unrelated_runs, _ = _page(request, parent=str(older_root.pk), limit=1)
    assert [item["id"] for item in unrelated_runs] == [str(older_root.template_id)]


def test_schedule_sidebar_keeps_native_admin_permissions(django_user_model, admin_user):
    schedule = _schedule(admin_user, label="Letters")
    staff = django_user_model.objects.create_user(username="schedule-reader", is_staff=True)
    request = _request(staff)
    assert _page(request) == ([], None)
    assert _page(request, parent=str(schedule.pk)) == ([], None)
    assert schedule_add_actions(request) == []

    staff.user_permissions.add(Permission.objects.get(codename="view_crawlschedule"))
    request.user = django_user_model.objects.get(pk=staff.pk)
    assert _page(request) == ([], None)

    staff.user_permissions.add(Permission.objects.get(codename="view_crawl"))
    request.user = django_user_model.objects.get(pk=staff.pk)
    rows, _ = _page(request)
    assert len(rows) == 1
    assert rows[0]["actions"] == [{"label": "View", "url": reverse("admin:crawls_crawlschedule_change", args=[str(schedule.pk)])}]
    assert schedule_add_actions(request) == []
    assert schedule_add_actions(_request(admin_user)) == [
        {"label": "New Scheduled Crawl", "url": reverse("admin:crawls_crawlschedule_add")},
    ]


def test_schedule_sidebar_query_is_bounded_with_many_roots_and_runs(admin_user):
    schedule = _schedule(admin_user, label="Archive feeds")
    CrawlSchedule.objects.bulk_create(
        [CrawlSchedule(created_by=admin_user, template=schedule.template, schedule="weekly", label=f"Schedule {i}") for i in range(240)],
    )
    Crawl.objects.bulk_create(
        [
            Crawl(created_by=admin_user, schedule=schedule, created_at=TICK + timedelta(seconds=i), urls="https://example.net/")
            for i in range(5000)
        ],
    )
    request = _request(admin_user)
    initial_time = perf_counter()
    with CaptureQueriesContext(connection) as captured:
        roots, root_cursor = _page(request, limit=20)
        runs, run_cursor = _page(request, parent=str(schedule.pk), limit=20)
        next_runs, _ = _page(request, parent=str(schedule.pk), cursor=run_cursor, limit=20)
    elapsed = (perf_counter() - initial_time) * 1000
    print(f"Scheduled crawl sidebar: 241 roots, 5,001 runs; root + two child pages in {elapsed:.1f} ms")
    assert root_cursor and run_cursor and len(roots) == len(runs) == len(next_runs) == 20
    assert not ({row["id"] for row in runs} & {row["id"] for row in next_runs})
    assert len(captured) == 3
    assert all("COUNT(" not in item["sql"].upper() and "LIMIT 21" in item["sql"].upper() for item in captured)
