import json
import time
from pathlib import Path

import pytest
from django.utils import timezone

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import run_archivebox_cmd
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
    start_archivebox_server,
    stop_server,
    wait_for_live_api,
    wait_for_snapshot_capture,
)


pytestmark = pytest.mark.django_db(transaction=True)


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


def _snapshot_hook_name(plugin_name: str) -> str:
    from abx_dl.models import discover_plugins

    plugin = discover_plugins().get(plugin_name)
    assert plugin is not None, f"missing test plugin {plugin_name}"
    hooks = plugin.filter_hooks("Snapshot")
    assert hooks, f"missing Snapshot hooks for {plugin_name}"
    return hooks[0].name


def _snapshot_state(cwd: Path, url: str) -> dict[str, object]:
    with use_archivebox_db(cwd):
        snapshot = Snapshot.objects.select_related("crawl", "crawl__created_by").get(url=url)
        snapshot_dir = Path(snapshot.output_dir)
        crawl_dir = Path(snapshot.crawl.output_dir)
        crawl_link = crawl_dir / "snapshots" / Snapshot.extract_domain_from_url(snapshot.url) / str(snapshot.id)
        results = list(
            ArchiveResult.objects.filter(snapshot=snapshot)
            .order_by("plugin", "hook_name")
            .values("plugin", "hook_name", "status", "output_files", "output_size"),
        )
        return {
            "id": str(snapshot.id),
            "crawl_id": str(snapshot.crawl_id),
            "status": snapshot.status,
            "retry_at": snapshot.retry_at,
            "downloaded_at": snapshot.downloaded_at,
            "output_size": snapshot.output_size,
            "snapshot_dir": snapshot_dir,
            "crawl_dir": crawl_dir,
            "crawl_link": crawl_link,
            "results": results,
        }


def _paused_snapshot_state(cwd: Path, snapshot_id: str) -> dict[str, object]:
    with use_archivebox_db(cwd):
        snapshot = Snapshot.objects.select_related("crawl").get(id=snapshot_id)
        succeeded_results = ArchiveResult.objects.filter(snapshot=snapshot, status=ArchiveResult.StatusChoices.SUCCEEDED).count()
        return {
            "status": snapshot.status,
            "retry_at": snapshot.retry_at,
            "crawl_status": snapshot.crawl.status,
            "succeeded_results": succeeded_results,
            "snapshot_dir": Path(snapshot.output_dir),
        }


def _wait_for_paused_scheduler_marker(cwd: Path, snapshot_id: str, timeout: int = 60) -> dict[str, object]:
    deadline = time.time() + timeout
    last_state: dict[str, object] = {}
    while time.time() < deadline:
        last_state = _paused_snapshot_state(cwd, snapshot_id)
        if last_state["status"] == Snapshot.StatusChoices.PAUSED and last_state["retry_at"] == RETRY_AT_MAX:
            return last_state
        if last_state["status"] == Snapshot.StatusChoices.SEALED:
            return last_state
        time.sleep(1)
    raise AssertionError(f"paused snapshot did not settle back to retry_at=MAX: {last_state}")


def _wait_for_crawl_snapshot_rows(cwd: Path, crawl_id: str, timeout: int = 45) -> dict[str, object]:
    deadline = time.time() + timeout
    latest_state: dict[str, object] | None = None
    while time.time() < deadline:
        latest_state = get_crawl_runtime_state(cwd, crawl_id)
        if latest_state["snapshots"]:
            return latest_state
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for snapshot rows for crawl {crawl_id}: {latest_state}")


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/snapshot-detail", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/snapshot-detail", crawl=crawl)

    response = client.get(f"/api/v1/core/snapshot/{snapshot.id}", **api_headers)

    assert response.status_code == 200, response.content


def test_snapshot_pause_resume_api_cascades_active_archiveresults_and_preserves_finished_rows(
    tmp_path,
    client,
    recursive_test_site,
):
    init_archive(tmp_path)
    api_token = create_admin_and_token(tmp_path)

    with use_archivebox_db(tmp_path):
        create_response = api_client_request(
            client,
            "post",
            "/api/v1/core/snapshots",
            api_token=api_token,
            payload={
                "url": recursive_test_site["root_url"],
                "depth": 0,
                "title": "Snapshot pause target",
                "tags": ["snapshot-pause-e2e"],
                "status": "queued",
            },
        )
        assert create_response.status_code == 200, create_response.content.decode()
        snapshot_id = json.loads(create_response.content.decode())["id"]
        snapshot = Snapshot.objects.get(id=snapshot_id)

        queued_result = _seed_archiveresult(
            snapshot,
            plugin="manualqueue",
            hook_name="on_Snapshot__manual_queue",
            status=ArchiveResult.StatusChoices.QUEUED,
        )
        started_result = _seed_archiveresult(
            snapshot,
            plugin="manualstart",
            hook_name="on_Snapshot__manual_start",
            status=ArchiveResult.StatusChoices.STARTED,
        )
        succeeded_result = _seed_archiveresult(
            snapshot,
            plugin="manualdone",
            hook_name="on_Snapshot__manual_done",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_text="finished result should stay finished",
            output_path="manualdone/final.txt",
        )
        failed_result = _seed_archiveresult(
            snapshot,
            plugin="manualfail",
            hook_name="on_Snapshot__manual_fail",
            status=ArchiveResult.StatusChoices.FAILED,
            output_text="failed result should stay failed",
        )

        invalid_response = api_client_request(
            client,
            "patch",
            f"/api/v1/core/snapshot/{snapshot_id}",
            api_token=api_token,
            payload={"action": "hold"},
        )
        assert invalid_response.status_code == 400
        snapshot = Snapshot.objects.get(id=snapshot_id)
        assert snapshot.status == Snapshot.StatusChoices.QUEUED

        pause_response = api_client_request(
            client,
            "patch",
            f"/api/v1/core/snapshot/{snapshot_id}",
            api_token=api_token,
            payload={"action": "pause"},
        )
        assert pause_response.status_code == 200, pause_response.content.decode()
        assert json.loads(pause_response.content.decode())["status"] == Snapshot.StatusChoices.PAUSED

        snapshot.refresh_from_db()
        crawl = Crawl.objects.get(id=snapshot.crawl_id)
        assert snapshot.status == Snapshot.StatusChoices.PAUSED
        assert snapshot.retry_at == RETRY_AT_MAX
        assert crawl.status == Crawl.StatusChoices.QUEUED

        active_rows = {
            row.plugin: (row.status, row.retry_at) for row in ArchiveResult.objects.filter(id__in=[queued_result.id, started_result.id])
        }
        assert active_rows == {
            "manualqueue": (ArchiveResult.StatusChoices.PAUSED, RETRY_AT_MAX),
            "manualstart": (ArchiveResult.StatusChoices.PAUSED, RETRY_AT_MAX),
        }

        finished_rows = {
            row.plugin: (row.status, row.retry_at, row.output_size)
            for row in ArchiveResult.objects.filter(id__in=[succeeded_result.id, failed_result.id])
        }
        assert finished_rows["manualdone"][0] == ArchiveResult.StatusChoices.SUCCEEDED
        assert finished_rows["manualdone"][1] is None
        assert finished_rows["manualdone"][2] == len("finished result should stay finished")
        assert finished_rows["manualfail"] == (ArchiveResult.StatusChoices.FAILED, None, 0)

        succeeded_row = ArchiveResult.objects.get(id=succeeded_result.id)
        output_path = Path(snapshot.output_dir) / next(iter(succeeded_row.output_files))
        assert output_path.read_text() == "finished result should stay finished"

        resume_response = api_client_request(
            client,
            "patch",
            f"/api/v1/core/snapshot/{snapshot_id}",
            api_token=api_token,
            payload={"action": "resume"},
        )
        assert resume_response.status_code == 200, resume_response.content.decode()
        assert json.loads(resume_response.content.decode())["status"] == Snapshot.StatusChoices.QUEUED

        snapshot.refresh_from_db()
        crawl.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.QUEUED
        assert snapshot.retry_at is not None
        assert snapshot.retry_at != RETRY_AT_MAX
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at is not None
        assert crawl.retry_at != RETRY_AT_MAX

        resumed_rows = {
            row.plugin: (row.status, row.retry_at) for row in ArchiveResult.objects.filter(id__in=[queued_result.id, started_result.id])
        }
        assert resumed_rows["manualqueue"][0] == ArchiveResult.StatusChoices.QUEUED
        assert resumed_rows["manualqueue"][1] is not None
        assert resumed_rows["manualqueue"][1] != RETRY_AT_MAX
        assert resumed_rows["manualstart"][0] == ArchiveResult.StatusChoices.QUEUED
        assert resumed_rows["manualstart"][1] is not None
        assert resumed_rows["manualstart"][1] != RETRY_AT_MAX

        assert ArchiveResult.objects.get(id=succeeded_result.id).status == ArchiveResult.StatusChoices.SUCCEEDED
        assert ArchiveResult.objects.get(id=failed_result.id).status == ArchiveResult.StatusChoices.FAILED
        assert output_path.read_text() == "finished result should stay finished"


def test_targeted_extract_retries_one_failed_archiveresult_while_snapshot_stays_paused(
    tmp_path,
    client,
    recursive_test_site,
):
    init_archive(tmp_path)
    api_token = create_admin_and_token(tmp_path)

    with use_archivebox_db(tmp_path):
        snapshot_response = api_client_request(
            client,
            "post",
            "/api/v1/core/snapshots",
            api_token=api_token,
            payload={
                "url": recursive_test_site["root_url"],
                "depth": 0,
                "title": "Paused targeted retry",
                "tags": ["targeted-extract-pause"],
                "status": "queued",
            },
        )
        assert snapshot_response.status_code == 200, snapshot_response.content.decode()
        snapshot_id = json.loads(snapshot_response.content.decode())["id"]
        snapshot = Snapshot.objects.get(id=snapshot_id)

        wget_result = _seed_archiveresult(
            snapshot,
            plugin="wget",
            hook_name=_snapshot_hook_name("wget"),
            status=ArchiveResult.StatusChoices.FAILED,
            output_text="initial failure before targeted retry",
        )
        unrelated_result = _seed_archiveresult(
            snapshot,
            plugin="manualqueue",
            hook_name="on_Snapshot__manual_queue",
            status=ArchiveResult.StatusChoices.QUEUED,
        )
        finished_result = _seed_archiveresult(
            snapshot,
            plugin="manualdone",
            hook_name="on_Snapshot__manual_done",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_text="finished row must survive targeted retry",
            output_path="manualdone/targeted.txt",
        )

        pause_response = api_client_request(
            client,
            "patch",
            f"/api/v1/core/snapshot/{snapshot_id}",
            api_token=api_token,
            payload={"action": "pause"},
        )
        assert pause_response.status_code == 200, pause_response.content.decode()
        assert json.loads(pause_response.content.decode())["status"] == Snapshot.StatusChoices.PAUSED

        snapshot = Snapshot.objects.get(id=snapshot_id)
        assert snapshot.status == Snapshot.StatusChoices.PAUSED
        assert snapshot.retry_at == RETRY_AT_MAX
        assert ArchiveResult.objects.get(id=wget_result.id).status == ArchiveResult.StatusChoices.FAILED
        assert ArchiveResult.objects.get(id=unrelated_result.id).status == ArchiveResult.StatusChoices.PAUSED
        finished_row = ArchiveResult.objects.get(id=finished_result.id)
        finished_output_path = Path(snapshot.output_dir) / next(iter(finished_row.output_files))
        assert finished_output_path.read_text() == "finished row must survive targeted retry"

    env = cli_env(
        port=get_free_port(),
        PLUGINS="wget",
        SAVE_WGET="True",
        WGET_WARC_ENABLED="False",
        URL_ALLOWLIST=r"127\.0\.0\.1[:/].*",
    )
    extract = run_archivebox_cmd(
        ["extract", str(wget_result.id)],
        cwd=tmp_path,
        env=env,
        timeout=150,
    )
    assert extract.returncode == 0, f"STDOUT:\n{extract.stdout}\nSTDERR:\n{extract.stderr}"

    with use_archivebox_db(tmp_path):
        snapshot = Snapshot.objects.get(id=snapshot_id)
        assert snapshot.status == Snapshot.StatusChoices.PAUSED
        assert snapshot.retry_at == RETRY_AT_MAX

        retried_wget = ArchiveResult.objects.get(id=wget_result.id)
        assert retried_wget.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert retried_wget.output_size > 0
        assert retried_wget.output_files

        unrelated = ArchiveResult.objects.get(id=unrelated_result.id)
        assert unrelated.status == ArchiveResult.StatusChoices.PAUSED
        assert unrelated.retry_at == RETRY_AT_MAX

        finished = ArchiveResult.objects.get(id=finished_result.id)
        assert finished.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert finished.retry_at is None
        assert finished_output_path.read_text() == "finished row must survive targeted retry"


@pytest.mark.timeout(240)
def test_paused_snapshot_survives_server_restart_and_resumes_via_api(client, tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(port=port, server=True, PLUGINS="wget", SAVE_WGET="True")
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
                "tags": ["snapshot-pause-restart-e2e"],
                "config": {"PLUGINS": "wget", "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*"},
            },
        )
        assert crawl_response.status_code == 200, crawl_response.content.decode()
        crawl_id = json.loads(crawl_response.content.decode())["id"]
        crawl = Crawl.objects.get(id=crawl_id)
        snapshot = Snapshot.objects.create(
            url=recursive_test_site["root_url"],
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        snapshot_id = str(snapshot.id)
        pause_response = api_client_request(
            client,
            "patch",
            f"/api/v1/core/snapshot/{snapshot_id}",
            api_token=api_token,
            payload={"action": "pause"},
        )
        assert pause_response.status_code == 200, pause_response.content.decode()

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)

        paused_state = _wait_for_paused_scheduler_marker(tmp_path, snapshot_id)
        assert paused_state["status"] == Snapshot.StatusChoices.PAUSED
        assert paused_state["succeeded_results"] == 0
        assert not list((paused_state["snapshot_dir"] / "wget").rglob("*.html"))

        stop_server(tmp_path)
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)

        restarted_state = _wait_for_paused_scheduler_marker(tmp_path, snapshot_id)
        assert restarted_state["status"] == Snapshot.StatusChoices.PAUSED
        assert restarted_state["succeeded_results"] == 0

        resume_response = live_api_request(
            port,
            "patch",
            f"/api/v1/core/snapshot/{snapshot_id}",
            api_token=api_token,
            json={"action": "resume"},
            timeout=10,
        )
        assert resume_response.status_code == 200, resume_response.text
        assert resume_response.json()["status"] == Snapshot.StatusChoices.QUEUED

        captured_text = wait_for_snapshot_capture(tmp_path, recursive_test_site["root_url"], timeout=180)
        assert "Root" in captured_text
        assert "About" in captured_text

        final_state = _snapshot_state(tmp_path, recursive_test_site["root_url"])
        assert final_state["status"] == Snapshot.StatusChoices.SEALED
        assert final_state["downloaded_at"] is not None
        assert any(
            result["plugin"] == "wget" and result["status"] == ArchiveResult.StatusChoices.SUCCEEDED for result in final_state["results"]
        )
    finally:
        stop_server(tmp_path)


def test_rest_snapshot_delete_removes_output_dir(client, api_headers):
    url = "https://example.com/delete-path-snapshot"

    response = api_client_request(
        client,
        "post",
        "/api/v1/core/snapshots",
        payload={"url": url, "depth": 0, "status": Snapshot.StatusChoices.QUEUED},
        headers=api_headers,
    )
    assert response.status_code == 200, response.content.decode()

    snapshot = Snapshot.objects.get(url=url)
    snapshot_dir = Path(snapshot.output_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "delete-path-test.txt").write_text("snapshot output")
    assert snapshot_dir.exists()

    response = client.delete(f"/api/v1/core/snapshot/{snapshot.id}", **api_headers)
    assert response.status_code == 200, response.content.decode()
    assert not Snapshot.objects.filter(pk=snapshot.pk).exists()
    assert not snapshot_dir.exists()
