"""Live progress UI tests."""

import subprocess
import uuid
from datetime import datetime, timezone as dt_timezone
from importlib.resources import files
from pathlib import Path
from threading import Thread

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from archivebox.tests.conftest import ADMIN_TEST_HOST
from archivebox.tests.conftest import cli_env, resolve_abxpkg_binary_env, run_archivebox_cmd
from archivebox.tests.test_archive_result_service import _run_shipped_snapshot_hook, _snapshot_hook_name

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def real_unscoped_hook_process(tmp_path):
    from archivebox.plugins.hooks import run_hook

    snap_dir = tmp_path / "snapshot"
    output_dir = snap_dir / "hashes"
    output_dir.mkdir(parents=True)
    (snap_dir / "source.txt").write_text("real live progress input", encoding="utf-8")
    hook_path = Path(str(files("abx_plugins.plugins.hashes").joinpath("on_Snapshot__93_hashes.py")))
    process = run_hook(
        hook_path,
        output_dir,
        config={"ABXPKG_LIB_DIR": str(tmp_path / "lib"), "SNAP_DIR": str(snap_dir)},
        timeout=30,
        url="https://example.com/live-progress",
    )
    process.refresh_from_db()
    assert process.exit_code == 0, process.stderr
    return process


@pytest.fixture
def real_snapshot_hook_projection(snapshot, cached_abxpkg_lib_dir):
    snap_dir = Path(snapshot.output_dir)
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "source.txt").write_text("real projected hook input", encoding="utf-8")
    return _run_shipped_snapshot_hook(
        snapshot,
        plugin="hashes",
        hook_name="on_Snapshot__93_hashes.py",
        lib_dir=cached_abxpkg_lib_dir,
    )


@pytest.fixture
def real_second_snapshot_hook_process(snapshot, tmp_path):
    from archivebox.plugins.hooks import run_hook

    snap_dir = Path(snapshot.output_dir)
    staticfile_dir = snap_dir / "staticfile"
    output_dir = snap_dir / "parse_txt_urls"
    staticfile_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (staticfile_dir / "input.txt").write_text("plain text without links", encoding="utf-8")
    hook_path = Path(str(files("abx_plugins.plugins.parse_txt_urls").joinpath("on_Snapshot__71_parse_txt_urls.py")))
    process = run_hook(
        hook_path,
        output_dir,
        config={"ABXPKG_LIB_DIR": str(tmp_path / "lib"), "SNAP_DIR": str(snap_dir)},
        timeout=30,
        url=snapshot.url,
    )
    process.refresh_from_db()
    assert process.exit_code == 0, process.stderr
    return process


@pytest.fixture
def real_crawl_setup_process(snapshot, hermetic_lib_dir):
    from archivebox.plugins.hooks import run_hook
    from archivebox.services.runner import run_install

    hook_path = Path(str(files("abx_plugins.plugins.chrome").joinpath("on_CrawlSetup__89_chrome_kill_zombies.js")))
    config_path = Path(str(files("abx_plugins.plugins.chrome").joinpath("config.json")))
    run_install(plugin_names=["chrome"])
    binary_env = resolve_abxpkg_binary_env(hermetic_lib_dir, deps_from=config_path)
    output_dir = Path(snapshot.crawl.output_dir) / "chrome"
    process = run_hook(
        hook_path,
        output_dir,
        config={
            **binary_env,
            "ABXPKG_LIB_DIR": str(hermetic_lib_dir),
            "CRAWL_DIR": str(snapshot.crawl.output_dir),
            "SNAP_DIR": str(snapshot.output_dir),
            "CHROME_USER_DATA_DIR": str(output_dir / "profile"),
        },
        timeout=30,
    )
    process.refresh_from_db()
    assert process.exit_code == 0, process.stderr
    return process


class TestLiveProgressView:
    def test_live_progress_rejects_unauthenticated_unscoped_request(self, client):
        response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 403
        assert response.json() == {"error": "Permission denied"}
        assert b"orchestrator_running" not in response.content
        assert b"active_crawls" not in response.content
        assert b"traceback" not in response.content

    def test_admin_live_progress_path_does_not_bypass_admin_auth(self, client):
        response = client.get("/admin/live-progress/", HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code in (302, 403, 404)
        assert b"orchestrator_running" not in response.content
        assert b"active_crawls" not in response.content
        assert b"traceback" not in response.content

    @override_settings(DEBUG=False)
    def test_live_progress_error_response_hides_traceback_without_debug(self, client, admin_user, crawl):
        from archivebox.crawls.models import Crawl

        Crawl.objects.filter(pk=crawl.pk).update(
            status=Crawl.StatusChoices.STARTED,
            config={"CRAWL_MAX_URLS": "not-an-integer"},
            retry_at=timezone.now(),
            modified_at=timezone.now(),
        )

        client.force_login(admin_user)
        response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 500
        payload = response.json()
        assert "error" in payload
        assert "traceback" not in payload
        assert payload["active_crawls"] == []

    def test_live_progress_excludes_old_archiveresults_from_previous_snapshot_run(
        self,
        client,
        admin_user,
        crawl,
        snapshot,
        real_snapshot_hook_projection,
    ):
        from datetime import timedelta
        from archivebox.core.models import ArchiveResult
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot

        client.force_login(admin_user)

        now = timezone.now()
        Crawl.objects.filter(pk=crawl.pk).update(
            status=Crawl.StatusChoices.STARTED,
            retry_at=now,
            modified_at=now,
        )
        Snapshot.objects.filter(pk=snapshot.pk).update(
            status=Snapshot.StatusChoices.STARTED,
            retry_at=None,
            downloaded_at=now - timedelta(minutes=1),
            modified_at=now,
        )

        old_process, finished_result = real_snapshot_hook_projection
        ArchiveResult.objects.filter(pk=finished_result.pk).update(
            start_ts=now - timedelta(hours=1, minutes=1),
            end_ts=now - timedelta(hours=1),
        )
        type(old_process).objects.filter(pk=old_process.pk).update(
            started_at=now - timedelta(hours=1, minutes=1),
            ended_at=now - timedelta(hours=1),
            modified_at=now - timedelta(hours=1),
        )
        snapshot.create_pending_archiveresults(hooks=[("chrome", "on_Snapshot__11_chrome_wait")])

        response = client.get("/progress.json", HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200, response.content
        payload = response.json()
        active_crawl = next(item for item in payload["active_crawls"] if item["id"] == str(crawl.pk))
        active_snapshot = next(item for item in active_crawl["active_snapshots"] if item["id"] == str(snapshot.pk))
        plugin_names = [item["plugin"] for item in active_snapshot["all_plugins"]]
        assert plugin_names == ["chrome"]

    def test_live_progress_does_not_hide_active_snapshot_results_when_modified_at_moves(
        self,
        client,
        admin_user,
        crawl,
        snapshot,
        blocking_http_server,
    ):
        from datetime import timedelta
        from archivebox.core.models import ArchiveResult
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
        from archivebox.services.runner import run_due_snapshot

        client.force_login(admin_user)

        now = timezone.now()
        Crawl.objects.filter(pk=crawl.pk).update(
            status=Crawl.StatusChoices.STARTED,
            retry_at=now,
            modified_at=now,
        )
        Snapshot.objects.filter(pk=snapshot.pk).update(
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=now,
            created_at=now - timedelta(hours=2),
            downloaded_at=None,
            url=blocking_http_server.url,
        )
        snapshot.refresh_from_db()
        [result] = snapshot.create_pending_archiveresults(hooks=[("wget", _snapshot_hook_name("wget"))])
        errors = []

        def run_snapshot():
            try:
                assert run_due_snapshot(snapshot, lock_seconds=60) is True
            except BaseException as err:
                errors.append(err)
            finally:
                blocking_http_server.request_started.set()

        runner = Thread(target=run_snapshot, name="archivebox-test-wget-runner")
        runner.start()
        try:
            blocking_http_server.request_started.wait()
            assert errors == []
            result.refresh_from_db()
            assert result.status == ArchiveResult.StatusChoices.STARTED
            Snapshot.objects.filter(pk=snapshot.pk).update(modified_at=timezone.now())

            response = client.get("/progress.json", HTTP_HOST=ADMIN_TEST_HOST)

            assert response.status_code == 200, response.content
            payload = response.json()
            active_crawl = next(item for item in payload["active_crawls"] if item["id"] == str(crawl.pk))
            active_snapshot = next(item for item in active_crawl["active_snapshots"] if item["id"] == str(snapshot.pk))
            plugin_names = [item["plugin"] for item in active_snapshot["all_plugins"]]
            assert plugin_names == ["wget"]
        finally:
            blocking_http_server.release_response.set()
            runner.join()

        assert errors == []
        result.refresh_from_db()
        assert result.status in (ArchiveResult.StatusChoices.SUCCEEDED, ArchiveResult.StatusChoices.NORESULTS)

    def test_live_progress_hides_finished_cancelled_crawl(self, client, admin_user, crawl, snapshot):
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl

        now = timezone.now()
        Crawl.objects.filter(pk=crawl.pk).update(
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
            modified_at=now,
        )
        Snapshot.objects.filter(pk=snapshot.pk).update(
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
            downloaded_at=None,
            modified_at=now,
        )
        snapshot.create_pending_archiveresults(hooks=[("singlefile", "on_Snapshot__50_singlefile")])

        client.force_login(admin_user)
        response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        payload = response.json()
        assert payload["active_crawls"] == []
        assert payload["downloads_queued"] == 0
        assert payload["crawls_active"] == 0
        assert payload["archiveresults_queued"] == 1
        assert "crawls_started" not in payload
        assert "crawls_pending" not in payload
        assert "downloads_started" not in payload
        assert "downloads_pending" not in payload

    def test_live_progress_scope_accepts_compact_and_dashed_snapshot_ids(self, client, admin_user, snapshot):
        from archivebox.core.models import Snapshot

        Snapshot.objects.filter(pk=snapshot.pk).update(status=Snapshot.StatusChoices.STARTED)
        compact_id = str(snapshot.id).replace("-", "")
        dashed_id = str(uuid.UUID(hex=compact_id))

        client.force_login(admin_user)
        for snapshot_id in (compact_id, dashed_id):
            response = client.get(reverse("live_progress"), {"snapshot_id": snapshot_id}, HTTP_HOST=ADMIN_TEST_HOST)
            assert response.status_code == 200
            payload = response.json()
            assert payload["scope"]["snapshot_id"] == compact_id
            assert payload["active_crawls"]

    def test_live_progress_scope_accepts_compact_and_dashed_crawl_ids(self, client, admin_user, crawl):
        compact_id = str(crawl.id).replace("-", "")
        dashed_id = str(uuid.UUID(hex=compact_id))

        client.force_login(admin_user)
        for crawl_id in (compact_id, dashed_id):
            response = client.get(reverse("live_progress"), {"crawl_id": crawl_id}, HTTP_HOST=ADMIN_TEST_HOST)
            assert response.status_code == 200
            payload = response.json()
            assert payload["scope"]["crawl_id"] == compact_id
            assert payload["active_crawls"]

    def test_live_progress_shows_old_paused_crawl_with_due_snapshot_work(self, client, admin_user, crawl, snapshot):
        from datetime import timedelta
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot

        old_timestamp = timezone.now() - timedelta(days=2)
        Crawl.objects.filter(pk=crawl.pk).update(
            status=Crawl.StatusChoices.PAUSED,
            created_at=old_timestamp,
            modified_at=old_timestamp,
            retry_at=None,
        )
        Snapshot.objects.filter(pk=snapshot.pk).update(
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
            modified_at=timezone.now(),
        )

        client.force_login(admin_user)
        response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200, response.content
        payload = response.json()
        active_crawl = next(item for item in payload["active_crawls"] if item["id"] == str(crawl.pk))
        assert active_crawl["status"] == Crawl.StatusChoices.PAUSED
        assert active_crawl["pending_snapshots"] == 1
        assert active_crawl["active_snapshots"] == [
            [
                str(snapshot.pk),
                "https://example.com",
            ],
        ]

    def test_live_progress_reports_real_orchestrator_process_running(
        self,
        client,
        admin_user,
        initialized_archive,
    ):
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Machine, Process, psutil

        machine_models._CURRENT_MACHINE = None
        cmd = ["archivebox", "manage", "shell"]
        popen = run_archivebox_cmd(
            ["manage", "shell"],
            cwd=initialized_archive,
            env=cli_env(live=True),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            capture_output=False,
            wait=False,
        )
        try:
            os_process = psutil.Process(popen.pid)
            Process.objects.create(
                machine=Machine.current(refresh=True),
                process_type=Process.TypeChoices.ORCHESTRATOR,
                status=Process.StatusChoices.RUNNING,
                pid=popen.pid,
                cmd=cmd,
                env={},
                started_at=datetime.fromtimestamp(os_process.create_time(), tz=dt_timezone.utc),
            )

            client.force_login(admin_user)
            response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_TEST_HOST)

            assert response.status_code == 200
            payload = response.json()
            assert payload["orchestrator_running"] is True
            assert payload["orchestrator_pid"] == popen.pid
        finally:
            assert popen.stdin is not None
            popen.stdin.close()
            popen.wait(timeout=20)

    def test_live_progress_ignores_unscoped_running_processes_when_no_crawls(
        self,
        client,
        admin_user,
        real_unscoped_hook_process,
    ):
        import os
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Process

        machine_models._CURRENT_MACHINE = None
        process = real_unscoped_hook_process
        process.status = Process.StatusChoices.RUNNING
        process.pid = os.getpid()
        process.ended_at = None
        process.save(update_fields=["status", "pid", "ended_at"])

        client.force_login(admin_user)
        response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        payload = response.json()
        assert payload["active_crawls"] == []
        assert payload["total_workers"] == 0

    def test_live_progress_does_not_clean_stale_running_processes(self, client, admin_user, real_unscoped_hook_process):
        from datetime import timedelta
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Process

        machine_models._CURRENT_MACHINE = None
        proc = real_unscoped_hook_process
        proc.status = Process.StatusChoices.RUNNING
        proc.pid = 999999
        proc.started_at = timezone.now() - timedelta(days=2)
        proc.ended_at = None
        proc.save(update_fields=["status", "pid", "started_at", "ended_at"])

        client.force_login(admin_user)
        response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        proc.refresh_from_db()
        assert proc.status == Process.StatusChoices.RUNNING
        assert proc.ended_at is None
        assert response.json()["total_workers"] == 0

    def test_live_progress_routes_crawl_process_rows_to_crawl_setup(
        self,
        client,
        admin_user,
        snapshot,
        real_crawl_setup_process,
    ):
        import os
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Process

        machine_models._CURRENT_MACHINE = None
        pid = os.getpid()
        process = real_crawl_setup_process
        process.status = Process.StatusChoices.RUNNING
        process.pid = pid
        process.ended_at = None
        process.save(update_fields=["status", "pid", "ended_at"])

        client.force_login(admin_user)
        response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(crawl for crawl in payload["active_crawls"] if crawl["id"] == str(snapshot.crawl_id))
        setup_entry = next(item for item in active_crawl["setup_plugins"] if item["source"] == "process")
        active_snapshot = next(item for item in active_crawl["active_snapshots"] if item["id"] == str(snapshot.id))
        assert setup_entry["label"] == "chrome kill zombies"
        assert setup_entry["status"] == "started"
        assert active_crawl["worker_pid"] == pid
        assert active_snapshot["all_plugins"] == []

    def test_live_progress_uses_snapshot_process_rows_before_archiveresults(
        self,
        client,
        admin_user,
        snapshot,
        real_snapshot_hook_projection,
    ):
        import os
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Process

        machine_models._CURRENT_MACHINE = None
        pid = os.getpid()
        process, result = real_snapshot_hook_projection
        result.delete()
        process.status = Process.StatusChoices.RUNNING
        process.pid = pid
        process.ended_at = None
        process.save(update_fields=["status", "pid", "ended_at"])

        client.force_login(admin_user)
        response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(crawl for crawl in payload["active_crawls"] if crawl["id"] == str(snapshot.crawl_id))
        active_snapshot = next(item for item in active_crawl["active_snapshots"] if item["id"] == str(snapshot.id))
        assert active_snapshot["all_plugins"][0]["source"] == "process"
        assert active_snapshot["all_plugins"][0]["label"] == "hashes"
        assert active_snapshot["all_plugins"][0]["status"] == "started"
        assert active_snapshot["worker_pid"] == pid

    def test_live_progress_merges_process_rows_with_archiveresults_when_present(
        self,
        client,
        admin_user,
        snapshot,
        real_snapshot_hook_projection,
        real_second_snapshot_hook_process,
    ):
        import os
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Process

        machine_models._CURRENT_MACHINE = None
        _, result = real_snapshot_hook_projection
        process = real_second_snapshot_hook_process
        process.status = Process.StatusChoices.RUNNING
        process.pid = os.getpid()
        process.exit_code = None
        process.started_at = timezone.now()
        process.ended_at = None
        process.save(update_fields=["status", "pid", "exit_code", "started_at", "ended_at", "modified_at"])

        client.force_login(admin_user)
        response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(crawl for crawl in payload["active_crawls"] if crawl["id"] == str(snapshot.crawl_id))
        active_snapshot = next(item for item in active_crawl["active_snapshots"] if item["id"] == str(snapshot.id))
        sources = {item["source"] for item in active_snapshot["all_plugins"]}
        plugins = {item["plugin"] for item in active_snapshot["all_plugins"]}
        assert sources == {"archiveresult", "process"}
        assert result.plugin in plugins
        assert "parse_txt_urls" in plugins

    def test_live_progress_omits_pid_for_exited_process_rows(
        self,
        client,
        admin_user,
        snapshot,
        real_second_snapshot_hook_process,
    ):
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Process

        machine_models._CURRENT_MACHINE = None
        process = real_second_snapshot_hook_process
        assert process.status == Process.StatusChoices.EXITED
        assert process.exit_code == 0
        type(snapshot).objects.filter(pk=snapshot.pk).update(downloaded_at=process.started_at + timezone.timedelta(seconds=1))

        client.force_login(admin_user)
        response = client.get(reverse("live_progress"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(crawl for crawl in payload["active_crawls"] if crawl["id"] == str(snapshot.crawl_id))
        active_snapshot = next(item for item in active_crawl["active_snapshots"] if item["id"] == str(snapshot.id))
        process_entry = next(item for item in active_snapshot["all_plugins"] if item["source"] == "process")
        assert process_entry["status"] == "succeeded"
        assert "pid" not in process_entry
