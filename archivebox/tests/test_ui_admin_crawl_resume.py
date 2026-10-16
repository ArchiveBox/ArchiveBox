"""Bulk Resume must requeue paused captures without rewriting their history."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST, cli_env, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("child_count", [1, 25])
def test_bulk_resume_requeues_paused_children_with_bounded_sql(admin_client, admin_user, child_count):
    selected = []
    for status in (Crawl.StatusChoices.PAUSED, Crawl.StatusChoices.SEALED):
        crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user, notes="keep parent notes")
        children = [
            Snapshot.objects.create(crawl=crawl, url=f"https://example.com/{index}", title="keep title") for index in range(child_count)
        ]
        assert crawl.pause()
        if status == Crawl.StatusChoices.SEALED:
            crawl.cancel()
        selected.append((crawl, children))

    untouched = Crawl.objects.create(urls="https://example.org/", created_by=admin_user)
    untouched_child = Snapshot.objects.create(crawl=untouched, url="https://example.org/")
    assert untouched.pause()
    active = Crawl.objects.create(urls="https://example.net/", created_by=admin_user)
    active_child = Snapshot.objects.create(crawl=active, url="https://example.net/")
    assert active_child.pause()
    sealed = Snapshot.objects.create(
        crawl=selected[0][0],
        url="https://example.com/sealed",
        status=Snapshot.StatusChoices.SEALED,
        retry_at=None,
    )
    result = ArchiveResult.objects.create(
        snapshot=selected[0][1][0],
        plugin="title",
        hook_name="on_Snapshot__01_title",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="previous title",
        output_size=14,
    )
    old_results = list(ArchiveResult.objects.order_by("pk").values())
    old_crawls = {row["id"]: row for row in Crawl.objects.values()}
    old_snapshots = {row["id"]: row for row in Snapshot.objects.values()}
    before = timezone.now()
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.post(
            reverse("admin:crawls_crawl_changelist"),
            {
                "action": "resume_selected_crawls",
                "_selected_action": [str(crawl.pk) for crawl, _ in selected] + [str(active.pk)],
                "index": "0",
            },
            HTTP_HOST=ADMIN_TEST_HOST,
        )
    after = timezone.now()
    assert response.status_code == 302
    for crawl, children in selected:
        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert before <= crawl.retry_at <= after
        for child in children:
            child.refresh_from_db()
            assert child.status == Snapshot.StatusChoices.QUEUED
            assert child.retry_at == crawl.retry_at

    changed_fields = {"status", "retry_at", "modified_at"}
    selected_ids = {crawl.pk for crawl, _ in selected}
    resumed_ids = {child.pk for _, children in selected for child in children}
    for model, old_rows, changed_ids in ((Crawl, old_crawls, selected_ids), (Snapshot, old_snapshots, resumed_ids)):
        for row in model.objects.values():
            old = old_rows[row["id"]]
            assert {key: value for key, value in row.items() if key not in changed_fields} == {
                key: value for key, value in old.items() if key not in changed_fields
            }
            if row["id"] not in changed_ids:
                assert row == old
    assert list(ArchiveResult.objects.order_by("pk").values()) == old_results
    assert ArchiveResult.objects.filter(pk=result.pk).exists()
    assert Snapshot.objects.filter(pk=sealed.pk, status=Snapshot.StatusChoices.SEALED).exists()
    assert Snapshot.objects.filter(pk=untouched_child.pk, status=Snapshot.StatusChoices.PAUSED).exists()
    scheduler_updates = [query["sql"] for query in queries if query["sql"].startswith(('UPDATE "crawls_crawl"', 'UPDATE "core_snapshot"'))]
    assert len(scheduler_updates) == 2
    assert not any('UPDATE "core_archiveresult"' in query["sql"] for query in queries)


def test_bulk_resume_restarts_real_runner_captures(initialized_archive, recursive_test_site, client):
    from django.contrib.auth import get_user_model

    env = cli_env(wget=True)
    with use_archivebox_db(initialized_archive):
        user = get_user_model().objects.create_superuser(username="resume_admin", password="testpassword")
        crawl = Crawl.objects.create(urls=recursive_test_site["root_url"], created_by=user, config={"PLUGINS": "wget"})
        child = crawl.create_snapshots_from_urls()[0]
        assert crawl.pause()
        client.force_login(user)
        response = client.post(
            reverse("admin:crawls_crawl_changelist"),
            {"action": "resume_selected_crawls", "_selected_action": str(crawl.pk), "index": "0"},
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        assert response.status_code == 302
        child.refresh_from_db()
        assert child.status == Snapshot.StatusChoices.QUEUED

    completed = run_archivebox_cmd(["run", f"--crawl-id={crawl.pk}"], cwd=initialized_archive, env=env, timeout=180)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    with use_archivebox_db(initialized_archive):
        child.refresh_from_db()
        crawl.refresh_from_db()
        assert child.status == Snapshot.StatusChoices.SEALED
        assert crawl.status == Crawl.StatusChoices.SEALED
        capture = child.archiveresult_set.get(plugin="wget", status=ArchiveResult.StatusChoices.SUCCEEDED)
        assert capture.output_files
        assert any(path.is_file() and b"<title>Root</title>" in path.read_bytes() for path in (child.output_dir / "wget").rglob("*.html"))
