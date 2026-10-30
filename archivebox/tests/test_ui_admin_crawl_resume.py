"""Bulk Resume must requeue paused captures without rewriting their history."""

import os
import signal
import sqlite3
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import (
    ADMIN_TEST_HOST,
    cleanup_process_group,
    cli_env,
    parse_jsonl_output,
    run_archivebox_cmd,
    wait_for_pid_to_disappear,
)
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
            if old_crawls[crawl.pk]["status"] == Crawl.StatusChoices.PAUSED:
                assert child.status == Snapshot.StatusChoices.QUEUED
                assert child.retry_at == crawl.retry_at
            else:
                assert Snapshot.objects.filter(pk=child.pk).values().get() == old_snapshots[child.pk]

    changed_fields = {"status", "retry_at", "modified_at"}
    selected_ids = {crawl.pk for crawl, _ in selected}
    resumed_ids = {
        child.pk for crawl, children in selected if old_crawls[crawl.pk]["status"] == Crawl.StatusChoices.PAUSED for child in children
    }
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


def test_bulk_resume_selected_all_uses_bounded_sql_parameters(admin_client, admin_user):
    from archivebox.workers.models import RETRY_AT_MAX

    crawls = Crawl.objects.bulk_create(
        [
            Crawl(
                urls=f"https://example.com/{index}",
                created_by=admin_user,
                status=Crawl.StatusChoices.PAUSED,
                retry_at=RETRY_AT_MAX,
            )
            for index in range(1205)
        ],
    )
    Snapshot.objects.bulk_create(
        [
            Snapshot(
                crawl=crawl,
                url=crawl.urls,
                timestamp=f"1700000000.{index:06d}",
                status=Snapshot.StatusChoices.PAUSED,
                retry_at=RETRY_AT_MAX,
            )
            for index, crawl in enumerate(crawls)
        ],
    )
    # SQLite builds differ in their variable limit. Exercise the supported
    # 999-variable limit with a real connection and an admin select-all POST.
    previous_limit = connection.connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
    try:
        with CaptureQueriesContext(connection) as queries:
            response = admin_client.post(
                reverse("admin:crawls_crawl_changelist"),
                {"action": "resume_selected_crawls", "_selected_action": str(crawls[0].pk), "select_across": "1", "index": "0"},
                HTTP_HOST=ADMIN_TEST_HOST,
            )
    finally:
        connection.connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, previous_limit)
    assert response.status_code == 302
    assert Crawl.objects.filter(status=Crawl.StatusChoices.QUEUED).count() == len(crawls)
    assert Snapshot.objects.filter(status=Snapshot.StatusChoices.QUEUED, retry_at__lte=timezone.now()).count() == len(crawls)
    scheduler_updates = [query["sql"] for query in queries if query["sql"].startswith(('UPDATE "crawls_crawl"', 'UPDATE "core_snapshot"'))]
    assert len(scheduler_updates) == 2


def test_bulk_resume_rolls_back_children_and_parents_when_parent_update_fails(admin_client, admin_user):
    crawls = [Crawl.objects.create(urls=f"https://example.com/{index}", created_by=admin_user) for index in range(2)]
    for crawl in crawls:
        Snapshot.objects.create(crawl=crawl, url=crawl.urls)
        assert crawl.pause()
    old_crawls = list(Crawl.objects.order_by("pk").values())
    old_snapshots = list(Snapshot.objects.order_by("pk").values())
    # A real SQLite constraint failure after earlier rows have been updated
    # must roll back the entire scheduling transition, including children.
    failing_id = sorted(crawl.pk.hex for crawl in crawls)[-1]
    with connection.cursor() as cursor:
        cursor.execute(
            f"""CREATE TRIGGER reject_crawl_resume BEFORE UPDATE ON crawls_crawl
                WHEN NEW.status = 'queued' AND OLD.id = '{failing_id}'
                BEGIN SELECT RAISE(ABORT, 'reject crawl resume'); END""",
        )
    try:
        with pytest.raises(IntegrityError, match="reject crawl resume"):
            admin_client.post(
                reverse("admin:crawls_crawl_changelist"),
                {"action": "resume_selected_crawls", "_selected_action": [str(crawl.pk) for crawl in crawls], "index": "0"},
                HTTP_HOST=ADMIN_TEST_HOST,
            )
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TRIGGER reject_crawl_resume")
    assert list(Crawl.objects.order_by("pk").values()) == old_crawls
    assert list(Snapshot.objects.order_by("pk").values()) == old_snapshots


def test_api_resume_rolls_back_parent_when_child_update_fails(client, api_headers, api_admin_user):
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=api_admin_user)
    Snapshot.objects.create(crawl=crawl, url=crawl.urls)
    assert crawl.pause()
    old_crawl = Crawl.objects.filter(pk=crawl.pk).values().get()
    old_snapshots = list(crawl.snapshot_set.values())
    with connection.cursor() as cursor:
        cursor.execute(
            """CREATE TRIGGER reject_snapshot_restart BEFORE UPDATE ON core_snapshot
                WHEN NEW.status = 'queued'
                BEGIN SELECT RAISE(ABORT, 'reject snapshot restart'); END""",
        )
    try:
        response = client.patch(
            f"/api/v1/crawls/crawl/{crawl.id}",
            data={"action": "resume"},
            content_type="application/json",
            **api_headers,
        )
        assert response.status_code == 503, response.content
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TRIGGER reject_snapshot_restart")
    assert Crawl.objects.filter(pk=crawl.pk).values().get() == old_crawl
    assert list(crawl.snapshot_set.values()) == old_snapshots
    response = client.patch(
        f"/api/v1/crawls/crawl/{crawl.id}",
        data={"action": "resume"},
        content_type="application/json",
        **api_headers,
    )
    assert response.status_code == 200, response.content
    crawl.refresh_from_db()
    child = crawl.snapshot_set.get()
    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert child.status == Snapshot.StatusChoices.QUEUED
    assert child.retry_at == crawl.retry_at


def test_crawl_resume_without_save_does_not_change_persisted_children(admin_user):
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
    Snapshot.objects.create(crawl=crawl, url=crawl.urls)
    assert crawl.pause()
    old_crawl = Crawl.objects.filter(pk=crawl.pk).values().get()
    old_snapshots = list(crawl.snapshot_set.values())
    assert crawl.resume(save=False)
    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert Crawl.objects.filter(pk=crawl.pk).values().get() == old_crawl
    assert list(crawl.snapshot_set.values()) == old_snapshots


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


@pytest.mark.timeout(180)
def test_bulk_resume_restarts_every_hook_of_interrupted_snapshot(initialized_archive, client):
    from django.contrib.auth import get_user_model

    from archivebox.machine.models import Process

    site = initialized_archive / "origin"
    site.mkdir()
    (site / "first.html").write_text("<html><title>Finished capture</title></html>")
    (site / "second.html").write_text("<html><title>Interrupted capture</title>" + "x" * 4000 + "</html>")
    icon = site / "favicon.ico"
    icon.write_bytes(b"first favicon")
    origin = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(site)))
    origin_thread = Thread(target=origin.serve_forever, daemon=True)
    origin_thread.start()
    base_url = f"http://127.0.0.1:{origin.server_port}"
    env = cli_env(
        wget=True,
        PLUGINS="wget,favicon",
        SAVE_FAVICON="True",
        FAVICON_PROVIDER="",
        WGET_ARGS_EXTRA='["--limit-rate=64"]',
        CRAWL_MAX_CONCURRENT_SNAPSHOTS="1",
        TIMEOUT="120",
    )
    runner = None
    hook_pid = None
    try:
        created = run_archivebox_cmd(
            ["crawl", "create", base_url + "/first.html", base_url + "/second.html"],
            cwd=initialized_archive,
            env=env,
        )
        assert created.returncode == 0, created.stdout + created.stderr
        crawl_id = next(record["id"] for record in parse_jsonl_output(created.stdout) if record.get("type") == "Crawl")
        runner = run_archivebox_cmd(
            ["run", f"--crawl-id={crawl_id}"],
            cwd=initialized_archive,
            env=env,
            wait=False,
            start_new_session=True,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            assert runner.poll() is None, runner.communicate()
            with use_archivebox_db(initialized_archive):
                finished = Snapshot.objects.filter(
                    crawl_id=crawl_id,
                    url=base_url + "/first.html",
                    status=Snapshot.StatusChoices.SEALED,
                ).first()
                interrupted = Snapshot.objects.filter(crawl_id=crawl_id, url=base_url + "/second.html").first()
                if finished and interrupted:
                    favicon = interrupted.archiveresult_set.filter(plugin="favicon", status=ArchiveResult.StatusChoices.SUCCEEDED).first()
                    wget = interrupted.archiveresult_set.filter(plugin="wget", process__status=Process.StatusChoices.RUNNING).first()
                    if favicon and wget and wget.process.pid:
                        hook_pid = wget.process.pid
                        break
            time.sleep(0.1)
        assert hook_pid, "wget did not remain in progress after the favicon hook completed"
        os.killpg(runner.pid, signal.SIGKILL)
        os.killpg(hook_pid, signal.SIGKILL)
        wait_for_pid_to_disappear(runner.pid)
        wait_for_pid_to_disappear(hook_pid)
        with use_archivebox_db(initialized_archive):
            interrupted.refresh_from_db()
            assert interrupted.status == Snapshot.StatusChoices.STARTED
            old_finished = Snapshot.objects.filter(pk=finished.pk).values().get()
            old_finished_results = list(finished.archiveresult_set.order_by("pk").values())
            old_finished_files = {
                path: path.read_bytes()
                for result in finished.archiveresult_set.all()
                for path in Path(result.pwd).rglob("*")
                if path.is_file()
            }
            old_results = {result.plugin: (result.pk, result.process_id) for result in interrupted.archiveresult_set.all()}
            saved_icon = Path(favicon.pwd) / "favicon.ico"
            assert saved_icon.read_bytes() == b"first favicon"
            user = get_user_model().objects.create_superuser(username="restart_admin", password="testpassword")
            client.force_login(user)
            response = client.post(
                reverse("admin:crawls_crawl_changelist"),
                {"action": "pause_selected_crawls", "_selected_action": crawl_id, "index": "0"},
                HTTP_HOST=ADMIN_TEST_HOST,
            )
            assert response.status_code == 302

        # Recovery observes the persisted parent pause and parks its interrupted
        # child, without rerunning hooks before the user resumes the crawl.
        paused = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=initialized_archive, env=env)
        assert paused.returncode == 0, paused.stdout + paused.stderr
        with use_archivebox_db(initialized_archive):
            interrupted.refresh_from_db()
            assert interrupted.status == Snapshot.StatusChoices.PAUSED
            scheduled_results = list(interrupted.archiveresult_set.order_by("pk").values())
            response = client.post(
                reverse("admin:crawls_crawl_changelist"),
                {"action": "resume_selected_crawls", "_selected_action": crawl_id, "index": "0"},
                HTTP_HOST=ADMIN_TEST_HOST,
            )
            assert response.status_code == 302
            interrupted.refresh_from_db()
            assert interrupted.status == Snapshot.StatusChoices.QUEUED
            assert list(interrupted.archiveresult_set.order_by("pk").values()) == scheduled_results
            assert saved_icon.read_bytes() == b"first favicon"

        icon.write_bytes(b"replacement favicon")
        (site / "second.html").write_text("<html><title>Restarted capture</title></html>")
        restarted = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=initialized_archive, env=env)
        assert restarted.returncode == 0, restarted.stdout + restarted.stderr
        with use_archivebox_db(initialized_archive):
            interrupted.refresh_from_db()
            assert interrupted.status == Snapshot.StatusChoices.SEALED
            assert Crawl.objects.get(pk=crawl_id).status == Crawl.StatusChoices.SEALED
            results = {result.plugin: result for result in interrupted.archiveresult_set.all()}
            assert set(results) == set(old_results) == {"wget", "favicon"}
            for plugin, result in results.items():
                assert result.pk == old_results[plugin][0]
                assert result.process_id != old_results[plugin][1]
                assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
                assert result.process.exit_code == 0
            assert saved_icon.read_bytes() == b"replacement favicon"
            assert any(b"<title>Restarted capture</title>" in path.read_bytes() for path in Path(results["wget"].pwd).rglob("*.html"))
            assert Snapshot.objects.filter(pk=finished.pk).values().get() == old_finished
            assert list(finished.archiveresult_set.order_by("pk").values()) == old_finished_results
            assert all(path.read_bytes() == content for path, content in old_finished_files.items())
    finally:
        cleanup_process_group(runner.pid if runner else None, hook_pid)
        origin.shutdown()
        origin.server_close()
        origin_thread.join(timeout=5)
