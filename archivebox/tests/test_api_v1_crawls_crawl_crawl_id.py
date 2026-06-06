import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import UserManager
from django.utils import timezone

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.test_orm_helpers import use_archivebox_db
from archivebox.workers.models import RETRY_AT_MAX

from .conftest import (
    api_client_request,
    cli_env,
    create_admin_and_token,
    get_crawl_runtime_state,
    get_free_port,
    init_archive,
    live_api_request,
    run_archivebox_cmd,
    start_archivebox_server,
    stop_server,
    wait_for_live_api,
    wait_for_snapshot_capture,
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


def _seed_archiveresult(
    snapshot: Snapshot,
    *,
    plugin: str,
    hook_name: str,
    status: str,
    output_text: str = "",
    output_path: str | None = None,
) -> ArchiveResult:
    output_files = {}
    output_size = 0
    output_mimetypes = ""
    if output_path is not None:
        output_bytes = output_text.encode()
        absolute_path = Path(snapshot.output_dir) / output_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(output_bytes)
        output_size = len(output_bytes)
        output_mimetypes = "text/plain"
        output_files[output_path] = {
            "extension": Path(output_path).suffix.lstrip("."),
            "mimetype": "text/plain",
            "size": output_size,
        }

    now = timezone.now()
    return ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin=plugin,
        hook_name=hook_name,
        status=status,
        output_str=output_path or output_text,
        output_files=output_files,
        output_size=output_size,
        output_mimetypes=output_mimetypes,
        start_ts=now if status != ArchiveResult.StatusChoices.QUEUED else None,
        end_ts=now if status in ArchiveResult.FINAL_STATES else None,
    )


def wait_for_crawl_snapshot_rows(cwd, crawl_id, timeout=45):
    deadline = time.time() + timeout
    latest_state = None
    while time.time() < deadline:
        latest_state = get_crawl_runtime_state(cwd, crawl_id)
        if latest_state["snapshots"]:
            return latest_state
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for runner to create snapshots for crawl {crawl_id}: {latest_state}")


def wait_for_crawl_child_snapshots_paused_or_sealed(cwd, crawl_id, timeout=45):
    deadline = time.time() + timeout
    latest_state = None
    while time.time() < deadline:
        latest_state = get_crawl_runtime_state(cwd, crawl_id)
        snapshots = latest_state["snapshots"]
        if snapshots and all(snapshot["status"] in {"paused", "sealed"} for snapshot in snapshots):
            return latest_state
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for runner to pause or seal snapshots for crawl {crawl_id}: {latest_state}")


def wait_for_crawl_wget_success_or_sealed(cwd, crawl_id, timeout=240):
    deadline = time.time() + timeout
    latest_state = None
    while time.time() < deadline:
        latest_state = get_crawl_runtime_state(cwd, crawl_id)
        wget_results = [result for result in latest_state["results"] if result["plugin"] == "wget"]
        if (
            latest_state["snapshots"]
            and latest_state["snapshots"][0]["status"] == "sealed"
            and any(result["status"] == "succeeded" and result["output_size"] > 0 for result in wget_results)
        ):
            return latest_state
        if (
            latest_state["crawl_status"] == "sealed"
            and latest_state["snapshots"]
            and latest_state["snapshots"][0]["status"] == "sealed"
            and all(result["status"] not in {"queued", "started", "paused"} for result in latest_state["results"])
        ):
            return latest_state
        time.sleep(2)
    raise AssertionError(f"timed out waiting for crawl resume completion for crawl {crawl_id}: {latest_state}")


def wait_for_sqlite_index_result(cwd, crawl_id, timeout=45):
    deadline = time.time() + timeout
    latest_state = None
    while time.time() < deadline:
        latest_state = get_crawl_runtime_state(cwd, crawl_id)
        final_results = [
            result
            for result in latest_state["results"]
            if result["plugin"] == "search_backend_sqlite" and result["status"] not in {"queued", "started", "paused"}
        ]
        if final_results:
            return latest_state
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for sqlite index result for crawl {crawl_id}: {latest_state}")


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


def test_crawl_pause_resume_api_cascades_archiveresults_and_leaves_finished_snapshot_results_alone(
    tmp_path,
    client,
    recursive_test_site,
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
                "urls": [recursive_test_site["root_url"]],
                "max_depth": 0,
                "tags": ["crawl-archiveresult-pause"],
                "config": {"PLUGINS": "wget", "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*"},
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
                "url": recursive_test_site["root_url"],
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
                "url": recursive_test_site["child_urls"][0],
                "crawl_id": crawl_id,
                "depth": 0,
                "title": "Already sealed child",
                "status": "queued",
            },
        )
        assert sealed_response.status_code == 200, sealed_response.content.decode()
        sealed_snapshot_id = json.loads(sealed_response.content.decode())["id"]
        sealed_snapshot = Snapshot.objects.get(id=sealed_snapshot_id)
        sealed_done = _seed_archiveresult(
            sealed_snapshot,
            plugin="sealedone",
            hook_name="on_Snapshot__sealed_done",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_text="sealed snapshot result remains finished",
            output_path="sealedone/final.txt",
        )
        sealed_snapshot.sm.seal()
        sealed_snapshot.refresh_from_db()
        assert sealed_snapshot.status == Snapshot.StatusChoices.SEALED
        assert sealed_snapshot.retry_at is None

        active_queued = _seed_archiveresult(
            active_snapshot,
            plugin="manualqueue",
            hook_name="on_Snapshot__manual_queue",
            status=ArchiveResult.StatusChoices.QUEUED,
        )
        active_started = _seed_archiveresult(
            active_snapshot,
            plugin="manualstart",
            hook_name="on_Snapshot__manual_start",
            status=ArchiveResult.StatusChoices.STARTED,
        )
        active_done = _seed_archiveresult(
            active_snapshot,
            plugin="manualdone",
            hook_name="on_Snapshot__manual_done",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_text="parent cascade should not rewrite finished rows",
            output_path="manualdone/cascade.txt",
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
        assert active_snapshot.status == Snapshot.StatusChoices.QUEUED
        assert active_snapshot.retry_at is not None
        assert active_snapshot.retry_at <= timezone.now()
        assert ArchiveResult.objects.get(id=active_queued.id).status == ArchiveResult.StatusChoices.QUEUED
        assert ArchiveResult.objects.get(id=active_started.id).status == ArchiveResult.StatusChoices.STARTED

        assert run_due_snapshot(active_snapshot, lock_seconds=60) is True
        active_snapshot.refresh_from_db()
        sealed_snapshot.refresh_from_db()
        assert active_snapshot.status == Snapshot.StatusChoices.PAUSED
        assert active_snapshot.retry_at == RETRY_AT_MAX
        assert sealed_snapshot.status == Snapshot.StatusChoices.SEALED
        assert sealed_snapshot.retry_at is None

        paused_rows = {
            row.plugin: (row.status, row.retry_at) for row in ArchiveResult.objects.filter(id__in=[active_queued.id, active_started.id])
        }
        assert paused_rows == {
            "manualqueue": (ArchiveResult.StatusChoices.PAUSED, RETRY_AT_MAX),
            "manualstart": (ArchiveResult.StatusChoices.PAUSED, RETRY_AT_MAX),
        }

        active_done_row = ArchiveResult.objects.get(id=active_done.id)
        sealed_done_row = ArchiveResult.objects.get(id=sealed_done.id)
        active_done_path = Path(active_snapshot.output_dir) / next(iter(active_done_row.output_files))
        sealed_done_path = Path(sealed_snapshot.output_dir) / next(iter(sealed_done_row.output_files))
        assert active_done_row.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert active_done_row.retry_at is None
        assert active_done_path.read_text() == "parent cascade should not rewrite finished rows"
        assert sealed_done_row.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert sealed_done_row.retry_at is None
        assert sealed_done_path.read_text() == "sealed snapshot result remains finished"

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
        assert resumed_rows["manualqueue"][0] == ArchiveResult.StatusChoices.QUEUED
        assert resumed_rows["manualqueue"][1] is not None
        assert resumed_rows["manualqueue"][1] != RETRY_AT_MAX
        assert resumed_rows["manualstart"][0] == ArchiveResult.StatusChoices.QUEUED
        assert resumed_rows["manualstart"][1] is not None
        assert resumed_rows["manualstart"][1] != RETRY_AT_MAX
        assert ArchiveResult.objects.get(id=active_done.id).status == ArchiveResult.StatusChoices.SUCCEEDED
        assert ArchiveResult.objects.get(id=sealed_done.id).status == ArchiveResult.StatusChoices.SUCCEEDED
        assert active_done_path.read_text() == "parent cascade should not rewrite finished rows"
        assert sealed_done_path.read_text() == "sealed snapshot result remains finished"


@pytest.mark.timeout(240)
def test_crawl_pause_resume_api_survives_server_restart_and_processes_after_resume(tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(port=port, server=True, PLUGINS="wget", SAVE_WGET="True")
    api_token = create_admin_and_token(tmp_path)

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)

        crawl_response = live_api_request(
            port,
            "post",
            "/api/v1/crawls/crawls",
            api_token=api_token,
            json={
                "urls": [recursive_test_site["root_url"]],
                "max_depth": 0,
                "tags": ["pause-resume-e2e"],
                "config": {"PLUGINS": "wget", "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*"},
            },
            timeout=10,
        )
        assert crawl_response.status_code == 200, crawl_response.text
        crawl_id = crawl_response.json()["id"]
        wait_for_crawl_snapshot_rows(tmp_path, crawl_id)

        pause_response = live_api_request(
            port,
            "patch",
            f"/api/v1/crawls/crawl/{crawl_id}",
            api_token=api_token,
            json={"action": "pause"},
            timeout=10,
        )
        assert pause_response.status_code == 200, pause_response.text
        assert pause_response.json()["status"] == "paused"

        paused_state = wait_for_crawl_child_snapshots_paused_or_sealed(tmp_path, crawl_id)
        assert paused_state["crawl_status"] == "paused"
        assert paused_state["crawl_retry_at"] == paused_state["retry_at_max"]
        assert len(paused_state["snapshots"]) == 1
        snapshot_finished_before_pause = paused_state["snapshots"][0]["status"] == "sealed"
        if snapshot_finished_before_pause:
            assert any(result["status"] == "succeeded" for result in paused_state["results"])
        else:
            assert paused_state["snapshots"][0]["status"] == "paused"
            assert paused_state["snapshots"][0]["retry_at"] == paused_state["retry_at_max"]

        stop_server(tmp_path)
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)

        restarted_state = get_crawl_runtime_state(tmp_path, crawl_id)
        assert restarted_state["crawl_status"] == "paused"
        assert restarted_state["crawl_retry_at"] == restarted_state["retry_at_max"]
        if snapshot_finished_before_pause:
            assert restarted_state["snapshots"][0]["status"] == "sealed"
            assert any(result["status"] == "succeeded" for result in restarted_state["results"])
            return
        assert restarted_state["snapshots"][0]["status"] == "paused"
        assert restarted_state["snapshots"][0]["retry_at"] == restarted_state["retry_at_max"]
        assert not any(result["status"] == "succeeded" for result in restarted_state["results"])

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

        captured_text = wait_for_snapshot_capture(tmp_path, recursive_test_site["root_url"], timeout=180)
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
def test_update_index_only_runs_paused_search_rows_and_resume_later_runs_crawl(tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(port=port, server=True, PLUGINS="wget", SAVE_WGET="True")
    api_token = create_admin_and_token(tmp_path)

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)

        crawl_response = live_api_request(
            port,
            "post",
            "/api/v1/crawls/crawls",
            api_token=api_token,
            json={
                "urls": [recursive_test_site["root_url"]],
                "max_depth": 0,
                "tags": ["paused-index-e2e"],
                "config": {"PLUGINS": "wget", "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*"},
            },
            timeout=10,
        )
        assert crawl_response.status_code == 200, crawl_response.text
        crawl_id = crawl_response.json()["id"]
        wait_for_crawl_snapshot_rows(tmp_path, crawl_id)

        pause_response = live_api_request(
            port,
            "patch",
            f"/api/v1/crawls/crawl/{crawl_id}",
            api_token=api_token,
            json={"action": "pause"},
            timeout=10,
        )
        assert pause_response.status_code == 200, pause_response.text
        paused_state = wait_for_crawl_child_snapshots_paused_or_sealed(tmp_path, crawl_id)
        snapshot_finished_before_pause = paused_state["snapshots"][0]["status"] == "sealed"
    finally:
        stop_server(tmp_path)

    if snapshot_finished_before_pause:
        indexed_state = get_crawl_runtime_state(tmp_path, crawl_id)
        assert indexed_state["crawl_status"] == "paused"
        assert indexed_state["snapshots"][0]["status"] == "sealed"
        return

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

    indexed_state = wait_for_sqlite_index_result(tmp_path, crawl_id)
    assert indexed_state["crawl_status"] == "paused"
    assert indexed_state["crawl_retry_at"] == indexed_state["retry_at_max"]
    assert indexed_state["snapshots"][0]["status"] == "paused"
    assert indexed_state["snapshots"][0]["retry_at"] == indexed_state["retry_at_max"]
    search_results = [result for result in indexed_state["results"] if result["plugin"] == "search_backend_sqlite"]
    assert search_results
    assert any(result["status"] not in {"queued", "started", "paused"} for result in search_results)

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)

        still_paused_state = get_crawl_runtime_state(tmp_path, crawl_id)
        assert still_paused_state["crawl_status"] == "paused"
        assert still_paused_state["snapshots"][0]["status"] == "paused"
        assert not any(result["plugin"] == "wget" and result["status"] == "succeeded" for result in still_paused_state["results"])

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

        resumed_state = wait_for_crawl_wget_success_or_sealed(tmp_path, crawl_id, timeout=240)

        assert resumed_state["snapshots"][0]["status"] == "sealed"
        wget_results = [result for result in resumed_state["results"] if result["plugin"] == "wget"]
        wget_succeeded = any(result["status"] == "succeeded" and result["output_size"] > 0 for result in wget_results)
        if wget_succeeded:
            captured_text = wait_for_snapshot_capture(tmp_path, recursive_test_site["root_url"], timeout=60)
            assert "Root" in captured_text
            assert "About" in captured_text
        else:
            assert resumed_state["crawl_status"] == "sealed"
            assert all(result["status"] not in {"queued", "started", "paused"} for result in resumed_state["results"])
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
