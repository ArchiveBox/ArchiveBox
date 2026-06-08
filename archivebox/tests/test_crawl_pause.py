import os
import subprocess
import sys
import time

import pytest
import requests
from django.utils import timezone

from archivebox.workers.models import RETRY_AT_MAX

from .conftest import (
    build_test_env,
    create_admin_and_token,
    get_crawl_runtime_state,
    get_free_port,
    init_archive,
    start_server,
    stop_server,
    wait_for_http,
    wait_for_snapshot_capture,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_retry_at_max_is_safe_for_admin_timezone_localization():
    with timezone.override("Pacific/Kiritimati"):
        assert timezone.localtime(RETRY_AT_MAX).year == 9999


def wait_for_crawl_snapshot_rows(cwd, crawl_id, timeout=45):
    deadline = time.time() + timeout
    latest_state = None
    while time.time() < deadline:
        latest_state = get_crawl_runtime_state(cwd, crawl_id)
        if latest_state["snapshots"]:
            return latest_state
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for runner to create snapshots for crawl {crawl_id}: {latest_state}")


@pytest.mark.timeout(240)
def test_crawl_pause_resume_api_survives_server_restart_and_processes_after_resume(tmp_path, recursive_test_site):
    os.chdir(tmp_path)
    init_archive(tmp_path)

    port = get_free_port()
    env = build_test_env(port, PLUGINS="wget", SAVE_WGET="True")
    api_token = create_admin_and_token(tmp_path)
    api_headers = {
        "Host": f"api.archivebox.localhost:{port}",
        "X-ArchiveBox-API-Key": api_token,
    }

    try:
        start_server(tmp_path, env=env, port=port)
        wait_for_http(port, host=f"api.archivebox.localhost:{port}", path="/api/v1/docs")

        crawl_response = requests.post(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawls",
            headers=api_headers,
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

        pause_response = requests.patch(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawl/{crawl_id}",
            headers=api_headers,
            json={"action": "pause"},
            timeout=10,
        )
        assert pause_response.status_code == 200, pause_response.text
        assert pause_response.json()["status"] == "paused"

        paused_state = get_crawl_runtime_state(tmp_path, crawl_id)
        assert paused_state["crawl_status"] == "paused"
        assert paused_state["crawl_retry_at"] == paused_state["retry_at_max"]
        assert len(paused_state["snapshots"]) == 1
        assert paused_state["snapshots"][0]["status"] == "paused"
        assert paused_state["snapshots"][0]["retry_at"] == paused_state["retry_at_max"]

        stop_server(tmp_path)
        start_server(tmp_path, env=env, port=port)
        wait_for_http(port, host=f"api.archivebox.localhost:{port}", path="/api/v1/docs")

        restarted_state = get_crawl_runtime_state(tmp_path, crawl_id)
        assert restarted_state["crawl_status"] == "paused"
        assert restarted_state["crawl_retry_at"] == restarted_state["retry_at_max"]
        assert restarted_state["snapshots"][0]["status"] == "paused"
        assert restarted_state["snapshots"][0]["retry_at"] == restarted_state["retry_at_max"]
        assert not any(result["status"] == "succeeded" for result in restarted_state["results"])

        resume_response = requests.patch(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawl/{crawl_id}",
            headers=api_headers,
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


@pytest.mark.timeout(180)
def test_update_index_only_runs_paused_search_rows_and_resume_later_runs_crawl(tmp_path, recursive_test_site):
    os.chdir(tmp_path)
    init_archive(tmp_path)

    port = get_free_port()
    env = build_test_env(port, PLUGINS="wget", SAVE_WGET="True")
    api_token = create_admin_and_token(tmp_path)
    api_headers = {
        "Host": f"api.archivebox.localhost:{port}",
        "X-ArchiveBox-API-Key": api_token,
    }

    try:
        start_server(tmp_path, env=env, port=port)
        wait_for_http(port, host=f"api.archivebox.localhost:{port}", path="/api/v1/docs")

        crawl_response = requests.post(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawls",
            headers=api_headers,
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

        pause_response = requests.patch(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawl/{crawl_id}",
            headers=api_headers,
            json={"action": "pause"},
            timeout=10,
        )
        assert pause_response.status_code == 200, pause_response.text
        assert pause_response.json()["status"] == "paused"
    finally:
        stop_server(tmp_path)

    update_env = build_test_env(
        port,
        PLUGINS="search_backend_sqlite",
        SEARCH_BACKEND_ENGINE="sqlite",
        USE_INDEXING_BACKEND="True",
        USE_SEARCHING_BACKEND="True",
    )
    update_process = subprocess.run(
        [
            sys.executable,
            "-m",
            "archivebox",
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
        capture_output=True,
        text=True,
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
    assert search_results
    assert all(result["status"] not in {"queued", "started", "paused"} for result in search_results)

    try:
        start_server(tmp_path, env=env, port=port)
        wait_for_http(port, host=f"api.archivebox.localhost:{port}", path="/api/v1/docs")

        still_paused_state = get_crawl_runtime_state(tmp_path, crawl_id)
        assert still_paused_state["crawl_status"] == "paused"
        assert still_paused_state["snapshots"][0]["status"] == "paused"
        assert not any(result["plugin"] == "wget" and result["status"] == "succeeded" for result in still_paused_state["results"])

        resume_response = requests.patch(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawl/{crawl_id}",
            headers=api_headers,
            json={"action": "resume"},
            timeout=10,
        )
        assert resume_response.status_code == 200, resume_response.text
        assert resume_response.json()["status"] == "queued"

        captured_text = wait_for_snapshot_capture(tmp_path, recursive_test_site["root_url"], timeout=180)
        assert "Root" in captured_text
        assert "About" in captured_text

        resumed_state = get_crawl_runtime_state(tmp_path, crawl_id)
        assert resumed_state["snapshots"][0]["status"] == "sealed"
        wget_results = [result for result in resumed_state["results"] if result["plugin"] == "wget"]
        assert wget_results
        assert any(result["status"] == "succeeded" and result["output_size"] > 0 for result in wget_results)
    finally:
        stop_server(tmp_path)
