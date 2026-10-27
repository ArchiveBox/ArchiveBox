import json
from datetime import timedelta
from pathlib import Path
from threading import Thread

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import run_archivebox_cmd
from archivebox.tests.test_archive_result_service import _run_shipped_snapshot_hook, _snapshot_hook_name
from archivebox.tests.test_orm_helpers import use_archivebox_db
from archivebox.workers.models import RETRY_AT_MAX

from .conftest import (
    api_client_request,
    cli_env,
    create_admin_and_token,
    get_snapshot_file_text,
    get_free_port,
    init_archive,
    live_api_request,
    start_archivebox_server,
    stop_server,
    wait_for_live_api,
)


pytestmark = pytest.mark.django_db(transaction=True)


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


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/snapshot-detail", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/snapshot-detail", crawl=crawl)

    response = client.get(f"/api/v1/core/snapshot/{snapshot.id}", **api_headers)

    assert response.status_code == 200, response.content


@pytest.mark.parametrize("endpoint", ["snapshot", "snapshots", "archiveresult", "archiveresults"])
def test_capture_metadata_does_not_load_crawl_intake(client, api_admin_user, api_headers, endpoint):
    from archivebox.core.models import Tag
    from archivebox.personas.models import Persona

    persona = Persona.objects.create(name="Metadata Owner", created_by=api_admin_user)
    # A historical import can contain megabytes of URLs. None of that intake is
    # part of an individual capture's metadata, even when it has many results.
    urls = "https://example.com/large-intake\n" * 40000
    crawl = Crawl.objects.create(urls=urls, created_by=api_admin_user, persona=persona)
    tag = Tag.objects.create(name="metadata", created_by=api_admin_user)
    snapshots = [Snapshot.objects.create(url=f"https://example.com/metadata/{index}", crawl=crawl) for index in range(3)]
    results = []
    for snapshot in snapshots:
        snapshot.tags.add(tag)
        for plugin in ("title", "dom", "singlefile"):
            results.append(ArchiveResult.objects.create(snapshot=snapshot, plugin=plugin, status="succeeded"))
    path = f"/api/v1/core/{endpoint}"
    if endpoint == "snapshot":
        path += f"/{snapshots[0].id}"
    elif endpoint == "archiveresult":
        path += f"/{results[0].id}"

    with CaptureQueriesContext(connection) as queries:
        response = client.get(path, {"with_archiveresults": "true"}, **api_headers)

    assert response.status_code == 200, response.content
    payload = response.json()
    items = payload["items"] if endpoint.endswith("s") else [payload]
    assert len(items) == {"snapshot": 1, "snapshots": 3, "archiveresult": 1, "archiveresults": 9}[endpoint]
    for item in items:
        assert item["created_by_id"] == str(api_admin_user.pk)
        assert item["created_by_username"] == api_admin_user.username
        if endpoint.startswith("snapshot"):
            assert item["persona"] == persona.name
            assert item["tags"] == [tag.name]
            assert item["num_archiveresults"] == 3
            assert {result["plugin"] for result in item["archiveresults"]} == {"title", "dom", "singlefile"}
            for result in item["archiveresults"]:
                assert result["created_by_username"] == api_admin_user.username
        else:
            assert item["snapshot_tags"] == [tag.name]
    selected = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith("SELECT")]
    assert not any('"urls"' in sql.split(" FROM ", 1)[0] for sql in selected), selected
    # Owner resolution must reuse joined rows, not reload the same full crawl
    # once per snapshot/result while serializing the response.
    assert not any(f'FROM "{Crawl._meta.db_table}"' in sql for sql in selected), selected
    assert sum('FROM "auth_user"' in sql for sql in selected) <= 1, selected
    crawl.refresh_from_db()
    assert crawl.urls == urls


@pytest.mark.parametrize("cmd", ['fetch_page_title("https://example.com/a path")', ["title", "https://example.com/a path"]])
def test_snapshot_detail_preserves_legacy_command_descriptions(client, api_admin_user, api_headers, cmd):
    from archivebox.machine.models import Machine, Process

    crawl = Crawl.objects.create(urls="https://example.com/legacy-command", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/legacy-command", crawl=crawl)
    process = Process.objects.create(machine=Machine.current(), cmd=cmd, status=Process.StatusChoices.EXITED)
    result = ArchiveResult.objects.create(snapshot=snapshot, plugin="title", process=process, status="succeeded")
    expected = [cmd] if isinstance(cmd, str) else cmd

    response = client.get(f"/api/v1/core/snapshot/{snapshot.id}", **api_headers)
    assert response.status_code == 200, response.content
    assert response.json()["archiveresults"][0]["cmd"] == expected
    response = client.get(f"/api/v1/core/archiveresult/{result.id}", **api_headers)
    assert response.status_code == 200, response.content
    assert response.json()["cmd"] == expected
    process.refresh_from_db()
    assert process.cmd == cmd, "Reading historical command metadata must not rewrite it"


@pytest.mark.parametrize("snapshot_ref", ["ffffffff-ffff-4fff-8fff-ffffffffffff", "ffffffffffff4fff8fffffffffffffff", "ffffffff"])
@pytest.mark.parametrize("method", ["get", "patch"])
def test_missing_snapshot_returns_not_found(client, api_headers, snapshot_ref, method):
    assert not Snapshot.objects.exists()
    kwargs = {"data": "{}", "content_type": "application/json"} if method == "patch" else {}
    response = getattr(client, method)(f"/api/v1/core/snapshot/{snapshot_ref}", **kwargs, **api_headers)
    assert response.status_code == 404, response.content
    assert response.json() == {"detail": "Snapshot not found"}
    assert not Snapshot.objects.exists()


@pytest.mark.parametrize("initial_status", ["queued", "started", "paused"])
@pytest.mark.parametrize("explicit_retry", [False, True])
def test_snapshot_status_patch_seals_persisted_state(client, api_headers, initial_status, explicit_retry):
    created = client.post(
        "/api/v1/core/snapshots",
        data=json.dumps({"url": "https://example.com/patch-seal", "status": initial_status, "tags": ["before"]}),
        content_type="application/json",
        **api_headers,
    )
    assert created.status_code == 200, created.content
    snapshot_id = created.json()["id"]
    path = f"/api/v1/core/snapshot/{snapshot_id}"
    original = client.get(path, **api_headers).json()
    assert original["status"] == initial_status
    assert original["retry_at"] is not None
    payload = {"status": "sealed", "tags": ["after"]}
    if explicit_retry:
        payload["retry_at"] = (timezone.now() + timedelta(hours=1)).isoformat()

    patched = client.patch(path, data=json.dumps(payload), content_type="application/json", **api_headers)
    assert patched.status_code == 200, patched.content
    assert patched.json()["status"] == "sealed"
    persisted = client.get(path, **api_headers)
    assert persisted.status_code == 200, persisted.content
    assert persisted.json()["status"] == "sealed"
    assert persisted.json()["retry_at"] is None
    assert persisted.json()["tags"] == ["after"]
    snapshot = Snapshot.objects.get(id=snapshot_id)
    assert snapshot.status == Snapshot.StatusChoices.SEALED
    assert snapshot.retry_at is None


@pytest.mark.parametrize("status", ["queued", "started", "paused"])
def test_snapshot_status_patch_preserves_nonfinal_updates(client, api_headers, status):
    created = client.post(
        "/api/v1/core/snapshots",
        data=json.dumps({"url": "https://example.com/patch-nonfinal", "status": "queued", "tags": ["before"]}),
        content_type="application/json",
        **api_headers,
    )
    assert created.status_code == 200, created.content
    snapshot_id = created.json()["id"]
    path = f"/api/v1/core/snapshot/{snapshot_id}"
    retry_at = timezone.now() + timedelta(hours=1)
    patched = client.patch(
        path,
        data=json.dumps({"status": status, "retry_at": retry_at.isoformat(), "tags": ["after"]}),
        content_type="application/json",
        **api_headers,
    )
    assert patched.status_code == 200, patched.content
    persisted = client.get(path, **api_headers)
    assert persisted.status_code == 200, persisted.content
    assert persisted.json()["status"] == status
    assert persisted.json()["tags"] == ["after"]
    snapshot = Snapshot.objects.get(id=snapshot_id)
    assert snapshot.status == status
    assert snapshot.retry_at == retry_at


def test_snapshot_pause_wins_over_concurrent_runner_lease(api_admin_user):
    crawl = Crawl.objects.create(urls="https://example.com/snapshot-pause-race", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/snapshot-pause-race", crawl=crawl)
    claimed_until = timezone.now() + timedelta(seconds=60)
    Snapshot.objects.filter(pk=snapshot.pk).update(retry_at=claimed_until)

    assert snapshot.pause() is True

    snapshot.refresh_from_db()
    assert snapshot.status == Snapshot.StatusChoices.PAUSED
    assert snapshot.retry_at == RETRY_AT_MAX


def test_snapshot_pause_resume_api_leaves_archiveresult_facts_unchanged(
    tmp_path,
    client,
    blocking_http_server,
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
                "url": blocking_http_server.url,
                "depth": 0,
                "title": "Snapshot pause target",
                "tags": ["snapshot-pause-e2e"],
                "status": "queued",
            },
        )
        assert create_response.status_code == 200, create_response.content.decode()
        snapshot_id = json.loads(create_response.content.decode())["id"]
        snapshot = Snapshot.objects.get(id=snapshot_id)
        from archivebox.config.common import get_config
        from archivebox.services.runner import run_due_snapshot

        lib_dir = get_config().ABXPKG_LIB_DIR
        snapshot.output_dir.mkdir(parents=True, exist_ok=True)
        (snapshot.output_dir / "source.txt").write_text("finished result should stay finished", encoding="utf-8")
        _succeeded_process, succeeded_result = _run_shipped_snapshot_hook(
            snapshot,
            plugin="hashes",
            hook_name="on_Snapshot__93_hashes.py",
            lib_dir=lib_dir,
        )
        Snapshot.objects.filter(pk=snapshot.pk).update(url="https://example.com/archivebox-test-repository.git")
        snapshot.refresh_from_db()
        _failed_process, failed_result = _run_shipped_snapshot_hook(
            snapshot,
            plugin="git",
            hook_name=_snapshot_hook_name("git"),
            event_hook_name=_snapshot_hook_name("git"),
            lib_dir=lib_dir,
            # file:// is intentionally noresults. Exercise a real Git fetch
            # failure using its transport policy, without depending on a server.
            env={
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "protocol.https.allow",
                "GIT_CONFIG_VALUE_0": "never",
            },
            expected_exit_codes=(1,),
        )
        assert failed_result.status == ArchiveResult.StatusChoices.FAILED
        assert failed_result.output_str == "git fetch failed (exit=128): fatal: transport 'https' not allowed"
        install_result = run_archivebox_cmd(["install", "wget"], cwd=tmp_path, timeout=600)
        assert install_result.returncode == 0, install_result.stderr or install_result.stdout
        now = timezone.now()
        Snapshot.objects.filter(pk=snapshot.pk).update(
            url=blocking_http_server.url,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=now,
            config={"PLUGINS": "wget"},
        )
        Crawl.objects.filter(pk=snapshot.crawl_id).update(status=Crawl.StatusChoices.STARTED, retry_at=now)
        snapshot.refresh_from_db()
        errors = []

        def run_snapshot():
            try:
                assert run_due_snapshot(snapshot, lock_seconds=60) is True
            except BaseException as err:
                errors.append(err)
            finally:
                blocking_http_server.request_started.set()

        runner = Thread(target=run_snapshot, name="archivebox-test-api-snapshot-wget-runner")
        runner.start()

        try:
            blocking_http_server.request_started.wait()
            assert errors == []
            started_result = ArchiveResult.objects.get(snapshot=snapshot, plugin="wget")
            assert started_result.status == ArchiveResult.StatusChoices.STARTED
            queued_result = ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin="parse_txt_urls",
                hook_name="on_Snapshot__71_parse_txt_urls",
                status=ArchiveResult.StatusChoices.QUEUED,
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
            assert snapshot.status == Snapshot.StatusChoices.STARTED

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
            assert crawl.status == Crawl.StatusChoices.STARTED

            active_rows = {
                row.plugin: (row.status, row.retry_at) for row in ArchiveResult.objects.filter(id__in=[queued_result.id, started_result.id])
            }
            assert active_rows == {
                "parse_txt_urls": (ArchiveResult.StatusChoices.QUEUED, None),
                "wget": (ArchiveResult.StatusChoices.STARTED, None),
            }

            finished_rows = {
                row.plugin: (row.status, row.retry_at, row.output_size)
                for row in ArchiveResult.objects.filter(id__in=[succeeded_result.id, failed_result.id])
            }
            assert finished_rows["hashes"][0] == ArchiveResult.StatusChoices.SUCCEEDED
            assert finished_rows["hashes"][1] is None
            assert finished_rows["hashes"][2] > 0
            assert finished_rows["git"][0] == ArchiveResult.StatusChoices.FAILED
            assert finished_rows["git"][1] is None

            succeeded_row = ArchiveResult.objects.get(id=succeeded_result.id)
            output_path = Path(snapshot.output_dir) / succeeded_row.plugin / next(iter(succeeded_row.output_files))
            assert output_path.is_file()

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
            assert crawl.status == Crawl.StatusChoices.STARTED
            assert crawl.retry_at is not None
            assert crawl.retry_at != RETRY_AT_MAX

            resumed_rows = {
                row.plugin: (row.status, row.retry_at) for row in ArchiveResult.objects.filter(id__in=[queued_result.id, started_result.id])
            }
            assert resumed_rows == active_rows

            assert ArchiveResult.objects.get(id=succeeded_result.id).status == ArchiveResult.StatusChoices.SUCCEEDED
            assert ArchiveResult.objects.get(id=failed_result.id).status == ArchiveResult.StatusChoices.FAILED
            assert output_path.is_file()
        finally:
            # The runner uses the collection DB from this context. Join it
            # before use_archivebox_db restores Django's shared DB settings;
            # a pytest finalizer runs too late and can race writes against the
            # restored/tearing-down test database (FOREIGN KEY failures).
            blocking_http_server.release_response.set()
            runner.join()
            assert errors == []


def test_targeted_extract_retries_one_failed_archiveresult_through_normal_snapshot_lifecycle(
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
        from archivebox.config.common import get_config

        lib_dir = get_config().ABXPKG_LIB_DIR
        Snapshot.objects.filter(pk=snapshot.pk).update(url="http://127.0.0.1:1/")
        snapshot.refresh_from_db()
        _wget_process, wget_result = _run_shipped_snapshot_hook(
            snapshot,
            plugin="wget",
            hook_name=_snapshot_hook_name("wget"),
            event_hook_name=_snapshot_hook_name("wget"),
            lib_dir=lib_dir,
            env={"WGET_WARC_ENABLED": "False"},
            expected_exit_codes=(1,),
        )
        assert wget_result.status == ArchiveResult.StatusChoices.FAILED
        assert "wget failed (exit=4)" in wget_result.output_str
        Snapshot.objects.filter(pk=snapshot.pk).update(url=recursive_test_site["root_url"])
        snapshot.refresh_from_db()
        unrelated_result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="parse_txt_urls",
            hook_name="on_Snapshot__71_parse_txt_urls",
            status=ArchiveResult.StatusChoices.QUEUED,
        )
        snapshot.output_dir.mkdir(parents=True, exist_ok=True)
        (snapshot.output_dir / "source.txt").write_text("finished row must survive targeted retry", encoding="utf-8")
        _finished_process, finished_result = _run_shipped_snapshot_hook(
            snapshot,
            plugin="hashes",
            hook_name="on_Snapshot__93_hashes.py",
            lib_dir=lib_dir,
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
        assert ArchiveResult.objects.get(id=unrelated_result.id).status == ArchiveResult.StatusChoices.QUEUED
        finished_row = ArchiveResult.objects.get(id=finished_result.id)
        finished_output_path = Path(snapshot.output_dir) / finished_row.plugin / next(iter(finished_row.output_files))
        assert finished_output_path.is_file()

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
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert snapshot.crawl.status == snapshot.crawl.StatusChoices.SEALED

        retried_wget = ArchiveResult.objects.get(id=wget_result.id)
        assert retried_wget.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert retried_wget.output_size > 0
        assert retried_wget.output_files

        unrelated = ArchiveResult.objects.get(id=unrelated_result.id)
        assert unrelated.status == ArchiveResult.StatusChoices.QUEUED
        assert unrelated.retry_at is None

        finished = ArchiveResult.objects.get(id=finished_result.id)
        assert finished.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert finished.retry_at is None
        assert finished_output_path.is_file()


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

        paused_state = _paused_snapshot_state(tmp_path, snapshot_id)
        assert paused_state["status"] == Snapshot.StatusChoices.PAUSED
        assert paused_state["succeeded_results"] == 0
        assert not list((paused_state["snapshot_dir"] / "wget").rglob("*.html"))

        stop_server(tmp_path)
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)

        restarted_state = _paused_snapshot_state(tmp_path, snapshot_id)
        assert restarted_state["status"] == Snapshot.StatusChoices.PAUSED
        assert restarted_state["succeeded_results"] == 0

        stop_runner_worker(tmp_path)
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

        stop_server(tmp_path)
        run_result = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=tmp_path, timeout=180, env=env)
        assert run_result.returncode == 0, run_result.stderr or run_result.stdout
        captured_text = get_snapshot_file_text(tmp_path, recursive_test_site["root_url"])
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


@pytest.mark.timeout(180)
def test_rest_snapshot_delete_removes_output_dir(tmp_path, recursive_test_site):
    import time
    from .test_snapshot_service import _snapshot_state
    from .conftest import create_admin_and_token, live_api_request, start_archivebox_server, stop_archivebox_process

    init_archive(tmp_path)
    port = get_free_port()
    env = cli_env(port=port, server=True, PLUGINS="wget")
    url = recursive_test_site["root_url"]
    captured = run_archivebox_cmd(["add", "--plugins=wget", url], cwd=tmp_path, env=env)
    assert captured.returncode == 0, captured.stdout + captured.stderr
    state = _snapshot_state(tmp_path, url)
    assert any("Root" in path.read_text(errors="ignore") for path in (state["snapshot_dir"] / "wget").rglob("*.html"))
    with use_archivebox_db(tmp_path):
        snapshot_id = str(Snapshot.objects.get(url=url).pk)
    token = create_admin_and_token(tmp_path)
    server = start_archivebox_server(tmp_path, port=port, env=env, log_name="api-delete-handoff.log")
    try:
        response = live_api_request(port, "delete", f"/api/v1/core/snapshot/{snapshot_id}", api_token=token)
        assert response.status_code == 200, response.text
        assert response.json()["queued_count"] == 1
        assert response.json()["deleted_count"] == 0
        deadline = time.monotonic() + 75
        with use_archivebox_db(tmp_path):
            while Snapshot.objects.filter(pk=snapshot_id).exists() and time.monotonic() < deadline:
                assert server.poll() is None
                time.sleep(0.1)
            assert not Snapshot.objects.filter(pk=snapshot_id).exists()
        assert not state["snapshot_dir"].exists()
        assert not state["crawl_link"].is_symlink()
        missing = live_api_request(port, "get", f"/api/v1/core/snapshot/{snapshot_id}", api_token=token)
        assert missing.status_code == 404
    finally:
        stop_archivebox_process(server)
