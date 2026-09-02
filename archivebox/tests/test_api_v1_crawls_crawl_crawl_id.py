import json
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread
from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import UserManager
from django.utils import timezone

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.test_orm_helpers import use_archivebox_db
from archivebox.tests.test_archive_result_service import _run_shipped_snapshot_hook
from archivebox.workers.models import RETRY_AT_MAX

from .conftest import (
    api_client_request,
    cli_env,
    create_admin_and_token,
    get_crawl_runtime_state,
    get_snapshot_file_text,
    get_free_port,
    init_archive,
    live_api_request,
    run_archivebox_cmd,
    start_archivebox_server,
    stop_server,
    wait_for_live_api,
)


pytestmark = pytest.mark.django_db(transaction=True)
User = get_user_model()
ADMIN_HOST = "admin.archivebox.localhost:8000"


@pytest.fixture
def other_user(db):
    return cast(UserManager, User.objects).create_user(
        username="rssother",
        email="rssother@test.com",
        password="testpassword",
    )


def stop_runner_worker(cwd: Path) -> None:
    script = """
from archivebox.workers.supervisord_util import get_existing_supervisord_process, stop_worker
supervisor = get_existing_supervisord_process()
assert supervisor is not None
stop_worker(supervisor, "worker_runner")
print("stopped")
"""
    result = run_archivebox_cmd(["manage", "shell", "-c", script], cwd=cwd, timeout=60)
    assert result.returncode == 0, result.stderr or result.stdout


def seed_paused_crawl(client, cwd: Path, api_token: str, url: str, tag: str) -> tuple[str, str]:
    from archivebox.services.runner import run_due_snapshot

    with use_archivebox_db(cwd):
        response = api_client_request(
            client,
            "post",
            "/api/v1/crawls/crawls",
            api_token=api_token,
            payload={
                "urls": [url],
                "max_depth": 0,
                "tags": [tag],
                "config": {"PLUGINS": "wget", "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*"},
            },
        )
        assert response.status_code == 200, response.content.decode()
        crawl_id = json.loads(response.content.decode())["id"]
        crawl = Crawl.objects.get(id=crawl_id)
        snapshot = Snapshot.objects.create(url=url, crawl=crawl, status=Snapshot.StatusChoices.QUEUED, retry_at=timezone.now())
        pause_response = api_client_request(
            client,
            "patch",
            f"/api/v1/crawls/crawl/{crawl_id}",
            api_token=api_token,
            payload={"action": "pause"},
        )
        assert pause_response.status_code == 200, pause_response.content.decode()
        assert run_due_snapshot(snapshot, lock_seconds=60)
        crawl.refresh_from_db()
        snapshot.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.PAUSED
        assert crawl.retry_at == RETRY_AT_MAX
        assert snapshot.status == Snapshot.StatusChoices.PAUSED
        assert snapshot.retry_at == RETRY_AT_MAX
        return str(crawl_id), str(snapshot.id)


def make_snapshot(*, user, url: str, title: str, bookmarked_at: datetime):
    crawl = Crawl.objects.create(urls=url, created_by=user)
    snapshot = Snapshot.objects.create(
        url=url,
        title=title,
        crawl=crawl,
        bookmarked_at=bookmarked_at,
    )
    return crawl, snapshot


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/crawl-detail", created_by=api_admin_user)

    response = client.get(f"/api/v1/crawls/crawl/{crawl.id}", **api_headers)

    assert response.status_code == 200, response.content


def test_create_crawl_rejects_multiline_url_item(client, api_headers):
    response = client.post(
        "/api/v1/crawls/crawls",
        data=json.dumps({"urls": ["https://example.com/one\nhttps://example.net/two"]}),
        content_type="application/json",
        **api_headers,
    )

    assert response.status_code == 400, response.content
    assert not Crawl.objects.exists()


def test_create_crawl_marks_structured_urls_as_url_list(client, api_headers):
    response = client.post(
        "/api/v1/crawls/crawls",
        data=json.dumps({"urls": ["https://example.com/one"], "config": {"PLUGINS": "title"}}),
        content_type="application/json",
        **api_headers,
    )

    assert response.status_code == 200, response.content
    crawl = Crawl.objects.get()
    assert crawl.urls == "https://example.com/one"
    assert crawl.config["PARSER"] == "url_list"


def test_create_crawl_preserves_explicit_parser(client, api_headers):
    response = client.post(
        "/api/v1/crawls/crawls",
        data=json.dumps({"urls": ["https://example.com/one"], "config": {"PARSER": "txt"}}),
        content_type="application/json",
        **api_headers,
    )

    assert response.status_code == 200, response.content
    assert Crawl.objects.get().config["PARSER"] == "txt"


def test_crawl_pause_wins_over_concurrent_runner_lease(api_admin_user):
    crawl = Crawl.objects.create(urls="https://example.com/crawl-pause-race", created_by=api_admin_user)
    claimed_until = timezone.now() + timedelta(seconds=60)
    Crawl.objects.filter(pk=crawl.pk).update(retry_at=claimed_until)

    assert crawl.pause() is True

    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.PAUSED
    assert crawl.retry_at == RETRY_AT_MAX


def test_crawl_pause_resume_api_leaves_archiveresult_facts_unchanged(
    request,
    tmp_path,
    client,
    blocking_http_server,
):
    init_archive(tmp_path)
    api_token = create_admin_and_token(tmp_path)

    with use_archivebox_db(tmp_path):
        crawl_response = api_client_request(
            client,
            "post",
            "/api/v1/crawls/crawls",
            api_token=api_token,
            payload={
                "urls": [blocking_http_server.url],
                "max_depth": 0,
                "tags": ["crawl-archiveresult-pause"],
                "config": {"PLUGINS": "wget,parse_txt_urls", "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*"},
            },
        )
        assert crawl_response.status_code == 200, crawl_response.content.decode()
        crawl_id = json.loads(crawl_response.content.decode())["id"]
        from archivebox.services.runner import run_due_snapshot

        active_response = api_client_request(
            client,
            "post",
            "/api/v1/core/snapshots",
            api_token=api_token,
            payload={
                "url": blocking_http_server.url,
                "crawl_id": crawl_id,
                "depth": 0,
                "title": "Active child",
                "status": "queued",
            },
        )
        assert active_response.status_code == 200, active_response.content.decode()
        active_snapshot = Snapshot.objects.get(id=json.loads(active_response.content.decode())["id"])

        sealed_response = api_client_request(
            client,
            "post",
            "/api/v1/core/snapshots",
            api_token=api_token,
            payload={
                "url": "https://example.com/already-sealed",
                "crawl_id": crawl_id,
                "depth": 0,
                "title": "Already sealed child",
                "status": "queued",
            },
        )
        assert sealed_response.status_code == 200, sealed_response.content.decode()
        sealed_snapshot_id = json.loads(sealed_response.content.decode())["id"]
        sealed_snapshot = Snapshot.objects.get(id=sealed_snapshot_id)
        from archivebox.config.common import get_config

        lib_dir = get_config().ABXPKG_LIB_DIR
        sealed_snapshot.output_dir.mkdir(parents=True, exist_ok=True)
        (sealed_snapshot.output_dir / "source.txt").write_text("sealed snapshot result remains finished", encoding="utf-8")
        _sealed_process, sealed_done = _run_shipped_snapshot_hook(
            sealed_snapshot,
            plugin="hashes",
            hook_name="on_Snapshot__93_hashes.py",
            lib_dir=lib_dir,
        )
        sealed_snapshot.seal()
        sealed_snapshot.refresh_from_db()
        assert sealed_snapshot.status == Snapshot.StatusChoices.SEALED
        assert sealed_snapshot.retry_at is None

        active_snapshot.output_dir.mkdir(parents=True, exist_ok=True)
        (active_snapshot.output_dir / "source.txt").write_text("parent cascade should not rewrite finished rows", encoding="utf-8")
        _active_done_process, active_done = _run_shipped_snapshot_hook(
            active_snapshot,
            plugin="hashes",
            hook_name="on_Snapshot__93_hashes.py",
            lib_dir=lib_dir,
        )
        now = timezone.now()
        Crawl.objects.filter(pk=crawl_id).update(status=Crawl.StatusChoices.STARTED, retry_at=now)
        Snapshot.objects.filter(pk=active_snapshot.pk).update(
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=now,
            config={"PLUGINS": "wget"},
        )
        active_snapshot.refresh_from_db()
        errors = []

        def run_snapshot():
            try:
                assert run_due_snapshot(active_snapshot, lock_seconds=60) is True
            except BaseException as err:
                errors.append(err)
            finally:
                blocking_http_server.request_started.set()

        runner = Thread(target=run_snapshot, name="archivebox-test-api-crawl-wget-runner")
        runner.start()

        def finish_runner():
            with use_archivebox_db(tmp_path):
                blocking_http_server.release_response.set()
                runner.join()
                assert errors == []

        request.addfinalizer(finish_runner)
        blocking_http_server.request_started.wait()
        assert errors == []
        active_started = ArchiveResult.objects.get(snapshot=active_snapshot, plugin="wget")
        assert active_started.status == ArchiveResult.StatusChoices.STARTED
        active_queued = ArchiveResult.objects.create(
            snapshot=active_snapshot,
            plugin="parse_txt_urls",
            hook_name="on_Snapshot__71_parse_txt_urls",
            status=ArchiveResult.StatusChoices.QUEUED,
        )
        pause_response = api_client_request(
            client,
            "patch",
            f"/api/v1/crawls/crawl/{crawl_id}",
            api_token=api_token,
            payload={"action": "pause"},
        )
        assert pause_response.status_code == 200, pause_response.content.decode()
        assert json.loads(pause_response.content.decode())["status"] == Crawl.StatusChoices.PAUSED

        active_snapshot.refresh_from_db()
        sealed_snapshot.refresh_from_db()
        crawl = Crawl.objects.get(id=crawl_id)
        assert crawl.status == Crawl.StatusChoices.PAUSED
        assert crawl.retry_at == RETRY_AT_MAX
        assert active_snapshot.status == Snapshot.StatusChoices.PAUSED
        assert active_snapshot.retry_at == RETRY_AT_MAX
        assert sealed_snapshot.status == Snapshot.StatusChoices.SEALED
        assert sealed_snapshot.retry_at is None

        unchanged_rows = {
            row.plugin: (row.status, row.retry_at) for row in ArchiveResult.objects.filter(id__in=[active_queued.id, active_started.id])
        }
        assert unchanged_rows["parse_txt_urls"] == (ArchiveResult.StatusChoices.QUEUED, None)
        assert unchanged_rows["wget"] == (ArchiveResult.StatusChoices.STARTED, None)

        active_done_row = ArchiveResult.objects.get(id=active_done.id)
        sealed_done_row = ArchiveResult.objects.get(id=sealed_done.id)
        active_done_path = Path(active_snapshot.output_dir) / active_done_row.plugin / next(iter(active_done_row.output_files))
        sealed_done_path = Path(sealed_snapshot.output_dir) / sealed_done_row.plugin / next(iter(sealed_done_row.output_files))
        assert active_done_row.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert active_done_row.retry_at is None
        assert active_done_path.is_file()
        assert sealed_done_row.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert sealed_done_row.retry_at is None
        assert sealed_done_path.is_file()

        resume_response = api_client_request(
            client,
            "patch",
            f"/api/v1/crawls/crawl/{crawl_id}",
            api_token=api_token,
            payload={"action": "resume"},
        )
        assert resume_response.status_code == 200, resume_response.content.decode()
        assert json.loads(resume_response.content.decode())["status"] == Crawl.StatusChoices.QUEUED

        active_snapshot.refresh_from_db()
        sealed_snapshot.refresh_from_db()
        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at is not None
        assert crawl.retry_at != RETRY_AT_MAX
        assert active_snapshot.status == Snapshot.StatusChoices.QUEUED
        assert active_snapshot.retry_at is not None
        assert active_snapshot.retry_at != RETRY_AT_MAX
        assert sealed_snapshot.status == Snapshot.StatusChoices.SEALED
        assert sealed_snapshot.retry_at is None

        resumed_rows = {
            row.plugin: (row.status, row.retry_at) for row in ArchiveResult.objects.filter(id__in=[active_queued.id, active_started.id])
        }
        assert resumed_rows == unchanged_rows
        assert ArchiveResult.objects.get(id=active_done.id).status == ArchiveResult.StatusChoices.SUCCEEDED
        assert ArchiveResult.objects.get(id=sealed_done.id).status == ArchiveResult.StatusChoices.SUCCEEDED
        assert active_done_path.is_file()
        assert sealed_done_path.is_file()

        blocking_http_server.release_response.set()
        runner.join()
        assert errors == []
        active_started.refresh_from_db()
        assert active_started.status in (ArchiveResult.StatusChoices.SUCCEEDED, ArchiveResult.StatusChoices.NORESULTS)
        assert ArchiveResult.objects.get(id=active_done.id).status == ArchiveResult.StatusChoices.SUCCEEDED
        assert ArchiveResult.objects.get(id=sealed_done.id).status == ArchiveResult.StatusChoices.SUCCEEDED


@pytest.mark.timeout(240)
def test_crawl_pause_resume_api_survives_server_restart_and_processes_after_resume(client, tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(port=port, server=True, PLUGINS="wget", SAVE_WGET="True")
    api_token = create_admin_and_token(tmp_path)
    crawl_id, _snapshot_id = seed_paused_crawl(client, tmp_path, api_token, recursive_test_site["root_url"], "pause-resume-e2e")

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)

        paused_state = get_crawl_runtime_state(tmp_path, crawl_id)
        assert paused_state["crawl_status"] == "paused"
        assert paused_state["crawl_retry_at"] == paused_state["retry_at_max"]
        assert len(paused_state["snapshots"]) == 1
        assert paused_state["snapshots"][0]["status"] == "paused"
        assert paused_state["snapshots"][0]["retry_at"] == paused_state["retry_at_max"]

        stop_server(tmp_path)
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)

        restarted_state = get_crawl_runtime_state(tmp_path, crawl_id)
        assert restarted_state["crawl_status"] == "paused"
        assert restarted_state["crawl_retry_at"] == restarted_state["retry_at_max"]
        assert restarted_state["snapshots"][0]["status"] == "paused"
        assert restarted_state["snapshots"][0]["retry_at"] == restarted_state["retry_at_max"]
        assert not any(result["status"] == "succeeded" for result in restarted_state["results"])

        stop_runner_worker(tmp_path)
        resume_response = live_api_request(
            port,
            "patch",
            f"/api/v1/crawls/crawl/{crawl_id}",
            api_token=api_token,
            json={"action": "resume"},
            timeout=10,
        )
        assert resume_response.status_code == 200, resume_response.text
        assert resume_response.json()["status"] == "queued"

        stop_server(tmp_path)
        run_result = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=tmp_path, timeout=180, env=env)
        assert run_result.returncode == 0, run_result.stderr or run_result.stdout
        captured_text = get_snapshot_file_text(tmp_path, recursive_test_site["root_url"])
        assert "Root" in captured_text
        assert "About" in captured_text

        final_state = get_crawl_runtime_state(tmp_path, crawl_id)
        assert final_state["snapshots"][0]["status"] == "sealed"
        wget_results = [result for result in final_state["results"] if result["plugin"] == "wget"]
        assert wget_results
        assert any(result["status"] == "succeeded" and result["output_size"] > 0 for result in wget_results)
    finally:
        stop_server(tmp_path)


@pytest.mark.timeout(420)
def test_update_index_only_leaves_paused_snapshot_on_normal_lifecycle_path(client, tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(port=port, server=True, PLUGINS="wget", SAVE_WGET="True")
    api_token = create_admin_and_token(tmp_path)
    crawl_id, _snapshot_id = seed_paused_crawl(client, tmp_path, api_token, recursive_test_site["root_url"], "paused-index-e2e")

    update_env = cli_env(
        port=port,
        PLUGINS="search_backend_sqlite",
        SEARCH_BACKEND_ENGINE="sqlite",
    )
    update_process = run_archivebox_cmd(
        [
            "update",
            "--index-only",
            "--crawl-id",
            crawl_id,
            "--limit",
            "1",
            "--batch-size",
            "1",
        ],
        cwd=tmp_path,
        env=update_env,
        timeout=120,
    )
    assert update_process.returncode == 0, update_process.stderr

    indexed_state = get_crawl_runtime_state(tmp_path, crawl_id)
    assert indexed_state["crawl_status"] == "paused"
    assert indexed_state["crawl_retry_at"] == indexed_state["retry_at_max"]
    assert indexed_state["snapshots"][0]["status"] == "paused"
    assert indexed_state["snapshots"][0]["retry_at"] == indexed_state["retry_at_max"]
    search_results = [result for result in indexed_state["results"] if result["plugin"] == "search_backend_sqlite"]
    assert search_results == []

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)

        still_paused_state = get_crawl_runtime_state(tmp_path, crawl_id)
        assert still_paused_state["crawl_status"] == "paused"
        assert still_paused_state["snapshots"][0]["status"] == "paused"
        assert not any(result["plugin"] == "wget" and result["status"] == "succeeded" for result in still_paused_state["results"])

        stop_runner_worker(tmp_path)
        resume_response = live_api_request(
            port,
            "patch",
            f"/api/v1/crawls/crawl/{crawl_id}",
            api_token=api_token,
            json={"action": "resume"},
            timeout=10,
        )
        assert resume_response.status_code == 200, resume_response.text
        assert resume_response.json()["status"] == "queued"

        stop_server(tmp_path)
        run_result = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=tmp_path, timeout=240, env=env)
        assert run_result.returncode == 0, run_result.stderr or run_result.stdout
        resumed_state = get_crawl_runtime_state(tmp_path, crawl_id)

        assert resumed_state["snapshots"][0]["status"] == "sealed"
        wget_results = [result for result in resumed_state["results"] if result["plugin"] == "wget"]
        assert any(result["status"] == "succeeded" and result["output_size"] > 0 for result in wget_results)
        captured_text = get_snapshot_file_text(tmp_path, recursive_test_site["root_url"])
        assert "Root" in captured_text
        assert "About" in captured_text
    finally:
        stop_server(tmp_path)


def test_crawl_cancel_api_defers_cleanup_to_runner(client, api_admin_user, api_headers):
    from archivebox.services.runner import run_due_crawl

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by=api_admin_user,
        status=Crawl.StatusChoices.STARTED,
        retry_at=timezone.now() + timedelta(minutes=5),
    )
    child = Snapshot.objects.create(
        url="https://example.com/cancel-child",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
        retry_at=timezone.now() + timedelta(minutes=5),
    )
    crawl.output_dir.mkdir(parents=True, exist_ok=True)
    pid_file = crawl.output_dir / "cleanup-test.pid"
    pid_file.write_text("12345")

    response = api_client_request(
        client,
        "patch",
        f"/api/v1/crawls/crawl/{crawl.id}",
        payload={"action": "cancel"},
        headers=api_headers,
    )
    assert response.status_code == 200, response.content

    crawl.refresh_from_db()
    child.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at is not None
    assert crawl.retry_at <= timezone.now()
    assert child.status == Snapshot.StatusChoices.STARTED
    assert child.retry_at is not None
    assert child.retry_at <= timezone.now()
    assert pid_file.exists()

    assert run_due_crawl(crawl, lock_seconds=60) is True
    crawl.refresh_from_db()
    assert crawl.retry_at is None
    assert not pid_file.exists()


def test_rest_crawl_delete_removes_crawl_and_snapshot_output_dirs(client, api_admin_user, api_headers):
    url = "https://example.com/delete-path-crawl"

    crawl = Crawl.objects.create(
        urls=url,
        max_depth=0,
        created_by=api_admin_user,
        status=Crawl.StatusChoices.SEALED,
    )
    snapshot = Snapshot.objects.create(
        crawl=crawl,
        url=url,
        depth=0,
        status=Snapshot.StatusChoices.SEALED,
    )
    crawl_dir = Path(crawl.output_dir)
    snapshot_dir = Path(snapshot.output_dir)
    crawl_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (crawl_dir / "delete-path-crawl.txt").write_text("crawl output")
    (snapshot_dir / "delete-path-snapshot.txt").write_text("snapshot output")
    assert crawl_dir.exists()
    assert snapshot_dir.exists()

    response = client.delete(f"/api/v1/crawls/crawl/{crawl.id}", **api_headers)
    assert response.status_code == 200, response.content.decode()
    assert not Crawl.objects.filter(pk=crawl.pk).exists()
    assert not Snapshot.objects.filter(pk=snapshot.pk).exists()
    assert not crawl_dir.exists()
    assert not snapshot_dir.exists()


def test_crawl_as_rss_redirects_to_canonical_snapshots_feed(client, api_token, api_admin_user, other_user):
    crawl, _snapshot = make_snapshot(
        user=api_admin_user,
        url="https://example.com/rss-crawl-feed",
        title="Crawl Feed Snapshot",
        bookmarked_at=timezone.make_aware(datetime(2026, 5, 23, 8, 0, 0)),
    )
    make_snapshot(
        user=other_user,
        url="https://example.com/rss-crawl-other",
        title="Other Crawl Snapshot",
        bookmarked_at=timezone.make_aware(datetime(2026, 5, 23, 9, 0, 0)),
    )

    response = client.get(
        f"/api/v1/crawls/crawl/{crawl.id}",
        {"as_rss": "true", "limit": 50, "api_key": api_token.token},
        HTTP_HOST=ADMIN_HOST,
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain
    redirect_url = response.redirect_chain[0][0]
    assert redirect_url.startswith("/api/v1/core/snapshots.rss?")
    assert f"crawl_id={crawl.id}" in redirect_url
    assert "as_rss" not in redirect_url
    assert response["Content-Type"].startswith("application/rss+xml")
    body = response.content.decode()
    assert "rss-crawl-feed" in body
    assert "rss-crawl-other" not in body
