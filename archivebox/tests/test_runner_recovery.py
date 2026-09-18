"""Real runner recovery, ownership, and lifecycle regression cases."""

import json
import os
import psutil
import pytest
import subprocess
from archivebox.base_models.models import get_or_create_system_user_pk
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.core.recovery_util import recover_orchestrator_state
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Machine, NetworkInterface, Process
from archivebox.services.runner import CrawlRunner, run_due_crawl, run_due_snapshot, run_pending_crawls
from archivebox.tests.conftest import (
    cleanup_process_group,
    cli_env,
    install_real_chrome,
    parse_jsonl_output,
    pid_is_alive,
    run_archivebox_cmd,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db
from archivebox.workers.models import RETRY_AT_MAX
from datetime import datetime, timedelta
from django.utils import timezone


@pytest.mark.django_db
class TestRecoverOrchestratorState:
    def test_recover_orchestrator_state_unlocks_started_crawl_with_pending_snapshot(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=None,
        )

        recovered = recover_orchestrator_state()

        crawl.refresh_from_db()
        assert recovered["crawls_started_with_due_snapshots"] == 1
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at is not None

    def test_recover_orchestrator_state_unlocks_started_crawl_with_finished_snapshots_for_runner(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )

        recovered = recover_orchestrator_state()

        crawl.refresh_from_db()
        assert "sealed_crawls" not in recovered
        assert recovered["crawls_started_without_active_snapshots"] == 1
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at is not None

        assert run_due_crawl(crawl, lock_seconds=60) is True
        crawl.refresh_from_db()

        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    def test_recover_orchestrator_state_repairs_retry_at_status_invariants(self):

        user_id = get_or_create_system_user_pk()
        queued_crawl = Crawl.objects.create(
            urls="https://example.com/queued-crawl",
            created_by_id=user_id,
            status=Crawl.StatusChoices.QUEUED,
            retry_at=None,
        )
        sealed_crawl = Crawl.objects.create(
            urls="https://example.com/sealed-crawl",
            created_by_id=user_id,
            status=Crawl.StatusChoices.SEALED,
            retry_at=timezone.now(),
        )
        queued_snapshot = Snapshot.objects.create(
            url="https://example.com/queued-snapshot",
            crawl=queued_crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=None,
        )
        sealed_snapshot = Snapshot.objects.create(
            url="https://example.com/sealed-snapshot",
            crawl=sealed_crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=timezone.now(),
        )

        recovered = recover_orchestrator_state()

        queued_crawl.refresh_from_db()
        sealed_crawl.refresh_from_db()
        queued_snapshot.refresh_from_db()
        sealed_snapshot.refresh_from_db()

        assert recovered["crawls_queued_without_retry_at"] == 1
        assert recovered["snapshots_queued_without_retry_at"] == 1
        assert queued_crawl.status == Crawl.StatusChoices.QUEUED
        assert queued_crawl.retry_at is not None
        assert sealed_crawl.status == Crawl.StatusChoices.SEALED
        assert sealed_crawl.retry_at is not None
        assert queued_snapshot.status == Snapshot.StatusChoices.QUEUED
        assert queued_snapshot.retry_at is not None
        assert sealed_snapshot.status == Snapshot.StatusChoices.SEALED
        assert sealed_snapshot.retry_at is not None

    def test_recover_orchestrator_state_leaves_due_queued_snapshot_for_runner_even_with_final_results(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.QUEUED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=None,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )

        recovered = recover_orchestrator_state()

        snapshot.refresh_from_db()
        crawl.refresh_from_db()

        assert "sealed_queued_snapshots" not in recovered
        assert "sealed_queued_crawls" not in recovered
        assert snapshot.status == Snapshot.StatusChoices.QUEUED
        assert snapshot.retry_at is not None
        assert snapshot.downloaded_at is None
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at is not None

    @pytest.mark.django_db(transaction=True)
    def test_recover_orchestrator_state_leaves_stale_queued_final_rows_for_runner(self):

        old = timezone.now() - timedelta(hours=13)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            config={"PLUGINS": "__archivebox_test_no_plugins__"},
            status=Crawl.StatusChoices.QUEUED,
            retry_at=old,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=old,
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )
        Crawl.objects.filter(pk=crawl.pk).update(modified_at=old)
        Snapshot.objects.filter(pk=snapshot.pk).update(modified_at=old)
        ArchiveResult.objects.filter(pk=result.pk).update(modified_at=old)

        recovered = recover_orchestrator_state()

        snapshot.refresh_from_db()
        crawl.refresh_from_db()

        assert "sealed_queued_snapshots" not in recovered
        assert "sealed_queued_crawls" not in recovered
        assert snapshot.status == Snapshot.StatusChoices.QUEUED
        assert snapshot.retry_at == old
        assert snapshot.downloaded_at is None
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at == old

        assert run_due_snapshot(snapshot, lock_seconds=60) is True
        snapshot.refresh_from_db()
        crawl.refresh_from_db()

        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    @pytest.mark.django_db(transaction=True)
    def test_run_due_snapshot_runs_snapshot_without_consulting_final_result_rows(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            config={"PLUGINS": "__archivebox_test_no_plugins__"},
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert snapshot.downloaded_at is not None

    def test_run_due_snapshot_pauses_child_when_parent_is_paused(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.PAUSED,
            retry_at=RETRY_AT_MAX,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.QUEUED,
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        snapshot.refresh_from_db()
        result.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.PAUSED
        assert snapshot.retry_at == RETRY_AT_MAX
        assert result.status == ArchiveResult.StatusChoices.QUEUED
        assert snapshot.archiveresult_set.count() == 1

    def test_parent_status_transitions_schedule_children_to_follow_parent_status(self):

        paused_crawl = Crawl.objects.create(
            urls="https://example.com/paused",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        paused_child = Snapshot.objects.create(
            url="https://example.com/paused",
            crawl=paused_crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        paused_result = ArchiveResult.objects.create(
            snapshot=paused_child,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.QUEUED,
        )
        paused_crawl.pause()

        sealed_crawl = Crawl.objects.create(
            urls="https://example.com/sealed",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        sealed_child = Snapshot.objects.create(
            url="https://example.com/sealed",
            crawl=sealed_crawl,
            status=Snapshot.StatusChoices.PAUSED,
            retry_at=RETRY_AT_MAX,
        )
        sealed_started_child = Snapshot.objects.create(
            url="https://example.com/sealed-started",
            crawl=sealed_crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        sealed_crawl.cancel()

        paused_child.refresh_from_db()
        paused_result.refresh_from_db()
        sealed_child.refresh_from_db()
        sealed_started_child.refresh_from_db()
        assert paused_child.status == Snapshot.StatusChoices.PAUSED
        assert paused_child.retry_at == RETRY_AT_MAX
        assert paused_result.status == ArchiveResult.StatusChoices.QUEUED
        assert sealed_child.status == Snapshot.StatusChoices.PAUSED
        assert sealed_child.retry_at is not None
        assert sealed_child.retry_at <= timezone.now()
        assert sealed_started_child.status == Snapshot.StatusChoices.STARTED
        assert sealed_started_child.retry_at is not None
        assert sealed_started_child.retry_at <= timezone.now()

        assert run_due_snapshot(sealed_child, lock_seconds=60) is True
        sealed_child.refresh_from_db()
        assert sealed_child.status == Snapshot.StatusChoices.SEALED
        assert sealed_child.retry_at is None

        assert run_due_snapshot(sealed_started_child, lock_seconds=60) is True
        sealed_started_child.refresh_from_db()
        assert sealed_started_child.status == Snapshot.StatusChoices.SEALED
        assert sealed_started_child.retry_at is None

    def test_recover_orchestrator_state_leaves_due_active_crawl_for_runner(self):

        old = timezone.now() - timedelta(hours=13)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.QUEUED,
            retry_at=old,
        )
        Crawl.objects.filter(id=crawl.id).update(modified_at=old, retry_at=old)

        recovered = recover_orchestrator_state()

        crawl.refresh_from_db()
        assert "stale_active_crawls_unlocked" not in recovered
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at == old

    def test_recover_orchestrator_state_unlocks_started_snapshot_without_running_result(self):

        future = timezone.now() + timedelta(seconds=45)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=future,
        )

        recovered = recover_orchestrator_state()

        snapshot.refresh_from_db()
        crawl.refresh_from_db()

        assert recovered["snapshots_started_without_running_results"] == 1
        assert "snapshots_active_under_sealed_crawls" not in recovered
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None
        assert snapshot.retry_at < future
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    def test_recover_orchestrator_state_unlocks_future_started_crawl_and_snapshot_after_owner_dies(self):

        future = timezone.now() + timedelta(seconds=45)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=future,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=future,
        )

        recovered = recover_orchestrator_state()

        crawl.refresh_from_db()
        snapshot.refresh_from_db()

        assert recovered["snapshots_started_without_running_results"] == 1
        assert recovered["crawls_started_with_due_snapshots"] == 1
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert crawl.retry_at is not None
        assert snapshot.retry_at is not None
        assert crawl.retry_at < future
        assert snapshot.retry_at < future

    def test_recover_orchestrator_state_preserves_future_started_snapshot_with_live_result_process(self, initialized_archive):

        worker = run_archivebox_cmd(
            ["manage", "shell"],
            cwd=initialized_archive,
            env=cli_env(live=True),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            capture_output=False,
            start_new_session=True,
            wait=False,
        )
        assert worker.stdin is not None
        assert pid_is_alive(worker.pid)
        try:
            future = timezone.now() + timedelta(seconds=45)
            crawl = Crawl.objects.create(
                urls="https://example.com",
                created_by_id=get_or_create_system_user_pk(),
                status=Crawl.StatusChoices.STARTED,
                retry_at=future,
            )
            snapshot = Snapshot.objects.create(
                url="https://example.com",
                crawl=crawl,
                status=Snapshot.StatusChoices.STARTED,
                retry_at=future,
            )
            process = Process.objects.create(
                machine=Machine.current(refresh=True),
                iface=NetworkInterface.current(refresh=True),
                process_type=Process.TypeChoices.HOOK,
                worker_type="archiveresult",
                pwd=str(snapshot.output_dir / "title"),
                cmd=[],
                status=Process.StatusChoices.RUNNING,
                retry_at=None,
                pid=worker.pid,
                started_at=timezone.now(),
                timeout=120,
            )
            ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin="title",
                hook_name="on_Snapshot__01_title",
                status=ArchiveResult.StatusChoices.STARTED,
                process=process,
            )

            recovered = recover_orchestrator_state()

            snapshot.refresh_from_db()
            assert recovered["snapshots_started_without_running_results"] == 0
            assert snapshot.status == Snapshot.StatusChoices.STARTED
            assert snapshot.retry_at == future
        finally:
            worker.stdin.close()
            worker.wait(timeout=20)
            assert not pid_is_alive(worker.pid)

    def test_recover_orchestrator_state_does_not_resume_paused_rows_with_max_retry_at(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.PAUSED,
            retry_at=RETRY_AT_MAX,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.PAUSED,
            retry_at=RETRY_AT_MAX,
        )

        recovered = recover_orchestrator_state()

        crawl.refresh_from_db()
        snapshot.refresh_from_db()

        assert recovered["crawls_started_with_due_snapshots"] == 0
        assert recovered["crawls_started_waiting_on_future_snapshots"] == 0
        assert recovered["crawls_started_without_active_snapshots"] == 0
        assert recovered["snapshots_started_without_running_results"] == 0
        assert crawl.status == Crawl.StatusChoices.PAUSED
        assert snapshot.status == Snapshot.StatusChoices.PAUSED
        assert crawl.retry_at == RETRY_AT_MAX
        assert snapshot.retry_at == RETRY_AT_MAX

    def test_recover_orchestrator_state_does_not_wake_sealed_snapshot_maintenance_rows(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="singlefile",
            hook_name="on_Snapshot__50_singlefile.py",
            status=ArchiveResult.StatusChoices.QUEUED,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="search_backend_sonic",
            hook_name="on_Snapshot__91_index_sonic",
            status=ArchiveResult.StatusChoices.QUEUED,
        )

        recovered = recover_orchestrator_state()

        snapshot.refresh_from_db()
        crawl.refresh_from_db()

        assert "snapshots_sealed_with_queued_results" not in recovered
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    def test_run_due_snapshot_finalizes_completed_upload_result_left_queued(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=timezone.now(),
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="dom",
            hook_name="on_Snapshot__archivebox_browser_extension_upload",
            status=ArchiveResult.StatusChoices.QUEUED,
            output_str="output.html",
            output_files={"output.html": {"extension": "html", "mimetype": "text/html", "size": 42}},
            output_size=42,
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        result.refresh_from_db()
        snapshot.refresh_from_db()
        assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert snapshot.retry_at is None

    @pytest.mark.django_db(transaction=True)
    def test_run_due_snapshot_keeps_extension_upload_and_runs_server_hooks(self):

        crawl = Crawl.objects.create(
            urls="https://example.com/extension-upload",
            created_by_id=get_or_create_system_user_pk(),
            config={"PLUGINS": "parse_txt_urls"},
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com/extension-upload",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )
        uploaded_result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="chrome_mhtml",
            hook_name="on_Snapshot__archivebox_browser_extension_upload",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_str="snapshot.mhtml",
            output_files={"snapshot.mhtml": {"extension": "mhtml", "mimetype": "multipart/related", "size": 42}},
            output_size=42,
        )

        recovered = recover_orchestrator_state()
        snapshot.refresh_from_db()
        crawl.refresh_from_db()
        assert recovered["snapshots_sealed_with_extension_uploads_only"] == 1
        assert snapshot.status == Snapshot.StatusChoices.QUEUED
        assert snapshot.retry_at is not None
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at is not None

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        snapshot.refresh_from_db()
        uploaded_result.refresh_from_db()
        server_results = snapshot.archiveresult_set.exclude(
            hook_name="on_Snapshot__archivebox_browser_extension_upload",
        )
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert uploaded_result.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert server_results.filter(plugin="parse_txt_urls").exists()
        assert not server_results.filter(
            status__in=(ArchiveResult.StatusChoices.QUEUED, ArchiveResult.StatusChoices.STARTED),
        ).exists()

    @pytest.mark.django_db(transaction=True)
    def test_run_due_snapshot_migrates_filesystem_before_returning_after_fast_finalize(self):

        crawl = Crawl.objects.create(
            urls="https://example.com/legacy-fast-finalize",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com/legacy-fast-finalize",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
            downloaded_at=timezone.now(),
        )
        Snapshot.objects.filter(pk=snapshot.pk).update(fs_version="0.8.0")
        snapshot.refresh_from_db()
        legacy_dir = snapshot.output_dir
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "index.html").write_text("legacy archive", encoding="utf-8")
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            hook_name="on_Snapshot__06_wget",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_str="index.html",
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.fs_version == Snapshot._fs_current_version()
        assert snapshot.output_dir.joinpath("index.html").read_text(encoding="utf-8") == "legacy archive"
        assert not legacy_dir.exists()

    @pytest.mark.django_db(transaction=True)
    def test_run_due_snapshot_migrates_filesystem_after_sealed_parent_reconciliation(self):

        crawl = Crawl.objects.create(
            urls="https://example.com/legacy-parent-sealed",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com/legacy-parent-sealed",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        Snapshot.objects.filter(pk=snapshot.pk).update(fs_version="0.8.0")
        snapshot.refresh_from_db()
        legacy_dir = snapshot.output_dir
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "index.html").write_text("legacy archive", encoding="utf-8")
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            hook_name="on_Snapshot__06_wget",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_str="index.html",
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.fs_version == Snapshot._fs_current_version()
        assert snapshot.output_dir.joinpath("index.html").read_text(encoding="utf-8") == "legacy archive"
        assert not legacy_dir.exists()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.timeout(300)
    @pytest.mark.parametrize("chrome_isolation", ["crawl", "snapshot"])
    def test_resume_queued_chrome_navigate_reruns_background_prerequisites(
        self,
        initialized_archive,
        recursive_test_site,
        chrome_isolation,
    ):

        env = cli_env(disable_extractors=True)
        env.update(
            {
                "SAVE_TITLE": "false",
                "TIMEOUT": "60",
                "CHROME_TIMEOUT": "30",
            },
        )
        install_real_chrome(initialized_archive, env, isolation=chrome_isolation)

        add_process = run_archivebox_cmd(
            [
                "add",
                "--depth=0",
                "--plugins=chrome",
                recursive_test_site["root_url"],
            ],
            cwd=initialized_archive,
            env=env,
            timeout=600,
        )
        assert add_process.returncode == 0, add_process.stderr or add_process.stdout

        list_process = run_archivebox_cmd(
            ["archiveresult", "list", "--plugin=chrome"],
            cwd=initialized_archive,
            env=env,
            timeout=60,
        )
        assert list_process.returncode == 0, list_process.stderr or list_process.stdout
        chrome_results = parse_jsonl_output(list_process.stdout)
        navigate_record = next(record for record in chrome_results if record["hook_name"] == "on_Snapshot__30_chrome_navigate")
        snapshot_id = navigate_record["snapshot_id"]

        with use_archivebox_db(initialized_archive):
            tab_result = ArchiveResult.objects.get(
                snapshot_id=snapshot_id,
                plugin="chrome",
                hook_name="on_Snapshot__01_chrome_tab.daemon.bg",
            )
            first_tab_process_id = tab_result.process_id
            assert first_tab_process_id is not None

        update_process = run_archivebox_cmd(
            ["archiveresult", "update", "--status=queued"],
            stdin=next(line for line in list_process.stdout.splitlines() if navigate_record["id"] in line) + "\n",
            cwd=initialized_archive,
            env=env,
            timeout=60,
        )
        assert update_process.returncode == 0, update_process.stderr or update_process.stdout

        run_process = run_archivebox_cmd(
            ["run"],
            cwd=initialized_archive,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            wait=False,
            start_new_session=True,
        )
        assert run_process.stdin is not None
        run_process.stdin.write(update_process.stdout)
        run_process.stdin.close()

        try:
            run_process.wait(timeout=120)
        finally:
            cleanup_process_group(run_process.pid)

        with use_archivebox_db(initialized_archive):
            navigate_result = ArchiveResult.objects.get(
                snapshot_id=snapshot_id,
                plugin="chrome",
                hook_name="on_Snapshot__30_chrome_navigate",
            )
            tab_result = ArchiveResult.objects.get(
                snapshot_id=snapshot_id,
                plugin="chrome",
                hook_name="on_Snapshot__01_chrome_tab.daemon.bg",
            )

        assert run_process.returncode == 0
        assert navigate_result.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert tab_result.process_id is not None
        assert tab_result.process_id != first_tab_process_id

    def test_recover_orchestrator_state_ignores_sealed_downloaded_snapshot_without_results(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            downloaded_at=timezone.now(),
            retry_at=None,
        )

        recovered = recover_orchestrator_state()

        snapshot.refresh_from_db()
        crawl.refresh_from_db()

        assert recovered["snapshots_started_without_running_results"] == 0
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    @pytest.mark.django_db(transaction=True)
    def test_recover_orchestrator_state_unlocks_started_snapshot_with_final_results_for_runner(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            config={"PLUGINS": "__archivebox_test_no_plugins__"},
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=None,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )

        recovered = recover_orchestrator_state()

        snapshot.refresh_from_db()
        assert "sealed_snapshots" not in recovered
        assert recovered["snapshots_started_without_running_results"] == 1
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None

        assert run_due_snapshot(snapshot, lock_seconds=60) is True
        snapshot.refresh_from_db()

        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None


@pytest.mark.django_db
class TestRunDueCrawlState:
    def test_idle_maintenance_repairs_archive_result_delete_at(self):

        crawl = Crawl.objects.create(
            urls="https://example.com/retention-repair",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
            config={"DELETE_AFTER": "2h"},
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com/retention-repair",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="search_backend_sqlite",
            hook_name="on_Snapshot__90_index_sqlite.py",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )

        # ArchiveResult saves are the plugin-event hot path. They intentionally
        # do not resolve parent Snapshot/Crawl config on every write; the real
        # runner's idle maintenance pass owns missing delete_at repair.
        assert result.delete_at is None
        assert run_pending_crawls(daemon=False, maintenance_only=True) == 0

        result.refresh_from_db()
        assert result.delete_at is not None

    def test_maintenance_only_runner_does_not_start_regular_queued_crawls(self):

        now = timezone.now()
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.QUEUED,
            retry_at=now,
        )

        assert run_pending_crawls(daemon=False, maintenance_only=True) == 0

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at == now
        assert crawl.snapshot_set.count() == 0

    def test_maintenance_only_runner_clears_snapshot_tick_without_scheduling_archive_results(self):

        now = timezone.now()
        crawl = Crawl.objects.create(
            urls="https://example.com/disabled-result",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com/disabled-result",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=now,
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="disabled_plugin",
            hook_name="on_Snapshot__50_disabled",
            status=ArchiveResult.StatusChoices.QUEUED,
        )

        assert run_pending_crawls(daemon=False, maintenance_only=True) == 0

        snapshot.refresh_from_db()
        result.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.fs_version == Snapshot._fs_current_version()
        assert snapshot.retry_at is None
        assert result.status == ArchiveResult.StatusChoices.QUEUED

    def test_snapshot_start_writes_short_future_lease(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )

        snapshot.advance_lifecycle()
        snapshot.refresh_from_db()

        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None
        assert snapshot.retry_at > timezone.now()

    def test_due_started_snapshot_with_live_child_extends_lease_without_reset(self):

        now = timezone.now()
        os_proc = psutil.Process(os.getpid())
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=now,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=now,
        )
        process = Process.objects.create(
            machine=Machine.current(),
            iface=NetworkInterface.current(),
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),
            started_at=datetime.fromtimestamp(os_proc.create_time(), tz=timezone.get_current_timezone()),
            cmd=os_proc.cmdline(),
            pwd=str(snapshot.output_dir / "title"),
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            process=process,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.STARTED,
            output_str="live work should not be reset",
            output_files={"partial.txt": {"size": 12}},
            output_size=12,
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        snapshot.refresh_from_db()
        result.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None
        assert snapshot.retry_at > now
        assert result.status == ArchiveResult.StatusChoices.STARTED
        assert result.output_str == "live work should not be reset"
        assert result.output_files == {"partial.txt": {"size": 12}}
        assert result.output_size == 12

    def test_run_due_crawl_seals_finished_started_crawl(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )

        assert run_due_crawl(crawl, lock_seconds=10) is True

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    @pytest.mark.parametrize(
        "retry_delay, snapshot_status",
        [
            (timedelta(hours=1), Snapshot.StatusChoices.QUEUED),
            (timedelta(minutes=5), Snapshot.StatusChoices.STARTED),
        ],
    )
    def test_run_due_crawl_preserves_future_snapshot_retry(self, retry_delay, snapshot_status):

        future = timezone.now() + retry_delay
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=snapshot_status,
            retry_at=future,
        )

        assert run_due_crawl(crawl, lock_seconds=10) is True

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at == future

    def test_run_due_crawl_unlocks_null_retry_queued_snapshot(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=None,
        )

        assert run_due_crawl(crawl, lock_seconds=10) is True

        crawl.refresh_from_db()
        snapshot.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at is not None
        assert snapshot.retry_at is not None


@pytest.mark.django_db
class TestRecoverOrchestratorStateRedFailureModes:
    def test_recovery_uses_newest_orphaned_process_for_exact_hook(self):

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(url="https://example.com", crawl=crawl, status=Snapshot.StatusChoices.SEALED, retry_at=None)
        machine = Machine.current(refresh=True)
        iface = NetworkInterface.current(refresh=True)
        hook_name = "on_Snapshot__01_title.daemon.bg"
        older_start = timezone.now() - timedelta(minutes=2)
        newer_start = timezone.now() - timedelta(minutes=1)

        for started_at, output_str in ((older_start, "older title"), (newer_start, "newer title")):
            records = [
                {
                    "type": "ArchiveResult",
                    "plugin": "title",
                    "hook_name": hook_name,
                    "status": "succeeded",
                    "output_str": output_str,
                    "output_json": {"title": output_str},
                },
            ]
            if started_at == newer_start:
                records.append(
                    {
                        "type": "ArchiveResult",
                        "plugin": "title",
                        "hook_name": "on_Snapshot__02_other_title_hook",
                        "status": "failed",
                        "output_str": "wrong hook",
                    },
                )
            Process.objects.create(
                machine=machine,
                iface=iface,
                process_type=Process.TypeChoices.HOOK,
                worker_type="archiveresult",
                pwd=str(snapshot.output_dir / "title"),
                cmd=[f"{hook_name}.py"],
                status=Process.StatusChoices.EXITED,
                retry_at=None,
                exit_code=0,
                started_at=started_at,
                ended_at=started_at + timedelta(seconds=1),
                stdout="\n".join(json.dumps(record) for record in records),
            )

        recovered = recover_orchestrator_state()

        assert recovered["archiveresults_missing_for_orphaned_hook_processes"] == 1
        assert ArchiveResult.objects.filter(snapshot=snapshot, plugin="title", hook_name=hook_name).count() == 1
        result = ArchiveResult.objects.get(snapshot=snapshot, plugin="title", hook_name=hook_name)
        assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert result.output_str == "newer title"
        assert result.output_json == {"title": "newer title"}
        assert result.start_ts == newer_start
        assert result.end_ts == newer_start + timedelta(seconds=1)
        assert result.process.started_at == newer_start

    def test_recovery_does_not_seal_queued_snapshot_waiting_for_future_retry_even_with_final_results(self):

        future = timezone.now() + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=future,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=future,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )

        recover_orchestrator_state()

        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.QUEUED
        assert snapshot.retry_at == future

    def test_recovery_does_not_seal_queued_crawl_waiting_for_future_retry_even_with_finished_snapshots(self):

        future = timezone.now() + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.QUEUED,
            retry_at=future,
        )
        Snapshot.objects.create(url="https://example.com", crawl=crawl, status=Snapshot.StatusChoices.SEALED, retry_at=None)

        recover_orchestrator_state()

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at == future

    def test_recovery_unlocks_started_parent_to_future_retry_child_not_now(self):

        future = timezone.now() + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://www.mathjax.org/",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        Snapshot.objects.create(url="https://www.mathjax.org/", crawl=crawl, status=Snapshot.StatusChoices.QUEUED, retry_at=future)

        recover_orchestrator_state()

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at == future

    def test_recovery_closes_interrupted_result_and_requeues_parent_snapshot(self):

        crawl = Crawl.objects.create(
            urls="https://www.mathjax.org/",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://www.mathjax.org/",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=None,
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.STARTED,
        )

        recover_orchestrator_state()

        result.refresh_from_db()
        snapshot.refresh_from_db()
        assert result.status == ArchiveResult.StatusChoices.FAILED
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None

    def test_recovery_closes_started_archiveresult_with_exited_process(self):

        crawl = Crawl.objects.create(
            urls="https://revealjs.com/",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(url="https://revealjs.com/", crawl=crawl, status=Snapshot.StatusChoices.STARTED, retry_at=None)
        process = Process.objects.create(
            machine=Machine.current(refresh=True),
            iface=NetworkInterface.current(refresh=True),
            process_type=Process.TypeChoices.HOOK,
            worker_type="archiveresult",
            pwd=str(snapshot.output_dir / "title"),
            cmd=["python", "--version"],
            status=Process.StatusChoices.EXITED,
            retry_at=None,
            exit_code=0,
            ended_at=timezone.now(),
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.STARTED,
            process=process,
        )

        recover_orchestrator_state()

        result.refresh_from_db()
        snapshot.refresh_from_db()
        assert result.status == ArchiveResult.StatusChoices.FAILED
        assert snapshot.retry_at is not None

    def test_recovery_does_not_reopen_sealed_snapshot_for_interrupted_result_projection(self):

        crawl = Crawl.objects.create(
            urls="https://pdfobject.com/pdf/sample-3pp.pdf",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://pdfobject.com/pdf/sample-3pp.pdf",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )
        process = Process.objects.create(
            machine=Machine.current(refresh=True),
            iface=NetworkInterface.current(refresh=True),
            process_type=Process.TypeChoices.HOOK,
            worker_type="archiveresult",
            pwd=str(snapshot.output_dir / "pdf"),
            cmd=["python", "--version"],
            status=Process.StatusChoices.EXITED,
            retry_at=None,
            exit_code=0,
            ended_at=timezone.now(),
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="pdf",
            hook_name="on_Snapshot__50_pdf",
            status=ArchiveResult.StatusChoices.STARTED,
            process=process,
        )

        recover_orchestrator_state()

        snapshot.refresh_from_db()
        result.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert result.status == ArchiveResult.StatusChoices.FAILED

    def test_recovery_closes_result_projection_before_unlocking_snapshot(self):

        crawl = Crawl.objects.create(
            urls="https://mermaid-js.github.io/mermaid/",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://mermaid-js.github.io/mermaid/",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=None,
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.STARTED,
        )

        recover_orchestrator_state()

        snapshot.refresh_from_db()
        result.refresh_from_db()
        assert result.status == ArchiveResult.StatusChoices.FAILED
        assert snapshot.retry_at is not None

    def test_crawl_runner_load_run_state_does_not_return_future_retry_snapshots(self):

        future = timezone.now() + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=future,
        )
        Snapshot.objects.create(url="https://example.com", crawl=crawl, status=Snapshot.StatusChoices.QUEUED, retry_at=future)

        runner = CrawlRunner(crawl, selected_plugins=[])

        assert runner.load_run_state() == []

    def test_crawl_runner_finalize_run_state_preserves_next_future_snapshot_retry(self):

        future = timezone.now() + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://blog.sweeting.me",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        Snapshot.objects.create(url="https://blog.sweeting.me", crawl=crawl, status=Snapshot.StatusChoices.QUEUED, retry_at=future)

        runner = CrawlRunner(crawl, selected_plugins=[])
        runner.finalize_run_state()

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at == future

    def test_due_started_crawl_yields_to_due_child_snapshot(self):

        now = timezone.now()
        crawl = Crawl.objects.create(
            urls="https://blog.sweeting.me",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=now,
        )
        snapshot = Snapshot.objects.create(
            url="https://blog.sweeting.me",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=now,
        )

        assert run_due_crawl(crawl, lock_seconds=10) is True

        crawl.refresh_from_db()
        snapshot.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at is not None
        assert crawl.retry_at > timezone.now()
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at == now

    def test_crawl_cancel_schedules_children_for_per_snapshot_sealing(self):

        now = timezone.now()
        past = now - timedelta(minutes=5)
        future = now + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://blog.sweeting.me",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=now,
        )
        queued = Snapshot.objects.create(
            url="https://blog.sweeting.me/queued",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=future,
        )
        started = Snapshot.objects.create(
            url="https://blog.sweeting.me/started",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=future,
        )
        paused = Snapshot.objects.create(
            url="https://blog.sweeting.me/paused",
            crawl=crawl,
            status=Snapshot.StatusChoices.PAUSED,
            retry_at=future,
        )
        already_due = Snapshot.objects.create(
            url="https://blog.sweeting.me/already-due",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=past,
        )
        maintenance = Snapshot.objects.create(
            url="https://blog.sweeting.me/maintenance",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=future,
        )
        ArchiveResult.objects.create(
            snapshot=maintenance,
            plugin="search_backend_sqlite",
            hook_name="on_Snapshot__90_index_sqlite",
            status=ArchiveResult.StatusChoices.QUEUED,
        )

        crawl.cancel()

        crawl.refresh_from_db()
        queued.refresh_from_db()
        started.refresh_from_db()
        paused.refresh_from_db()
        maintenance.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is not None
        assert crawl.retry_at <= timezone.now()
        for snapshot in (queued, started, paused, already_due):
            assert snapshot.status != Snapshot.StatusChoices.SEALED
            assert snapshot.retry_at is not None
            assert snapshot.retry_at <= timezone.now()
            assert run_due_snapshot(snapshot, lock_seconds=60) is True
            snapshot.refresh_from_db()
            assert snapshot.status == Snapshot.StatusChoices.SEALED
            assert snapshot.retry_at is None
        assert maintenance.status == Snapshot.StatusChoices.SEALED
        assert maintenance.retry_at == future
        assert run_due_crawl(crawl, lock_seconds=60) is True
        crawl.refresh_from_db()
        assert crawl.retry_at is None

    def test_crawl_cancel_reschedules_children_when_parent_was_already_sealed(self):

        future = timezone.now() + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://blog.sweeting.me",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://blog.sweeting.me/old-cancel",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=future,
        )

        crawl.cancel()

        crawl.refresh_from_db()
        snapshot.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None
        assert snapshot.retry_at <= timezone.now()

        snapshot.status = Snapshot.StatusChoices.SEALED
        snapshot.retry_at = None
        snapshot.save(update_fields=["status", "retry_at", "modified_at"])
        crawl.refresh_from_db()
        sealed_modified_at = crawl.modified_at

        crawl.cancel()

        crawl.refresh_from_db()
        assert crawl.modified_at == sealed_modified_at

    def test_run_due_crawl_stale_started_object_cannot_resurrect_cancelled_crawl(self):

        now = timezone.now()
        crawl = Crawl.objects.create(
            urls="https://blog.sweeting.me",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=now,
        )
        Snapshot.objects.create(
            url="https://blog.sweeting.me/queued",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=now,
        )
        stale_crawl = Crawl.objects.get(pk=crawl.pk)

        crawl.cancel()
        assert run_due_crawl(stale_crawl, lock_seconds=60) is True

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    def test_snapshot_seal_uses_retry_at_ownership_not_modified_at(self):

        now = timezone.now()
        crawl = Crawl.objects.create(
            urls="https://blog.sweeting.me",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://blog.sweeting.me/owned-seal",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=now,
        )

        assert Snapshot.claim_for_worker(snapshot, lock_seconds=60) is True
        Snapshot.objects.filter(pk=snapshot.pk).update(
            downloaded_at=now,
            modified_at=now + timedelta(seconds=1),
        )

        snapshot.seal()
        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert snapshot.downloaded_at == now

    def test_recovery_reschedules_stale_due_crawl_even_with_unrelated_process_path_containing_crawl_id(self):

        old = timezone.now() - timedelta(hours=13)
        crawl = Crawl.objects.create(
            urls="https://github.com/nodeca/pica",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.QUEUED,
            retry_at=old,
        )
        Crawl.objects.filter(id=crawl.id).update(modified_at=old, retry_at=old)
        Process.objects.create(
            machine=Machine.current(refresh=True),
            iface=NetworkInterface.current(refresh=True),
            process_type=Process.TypeChoices.HOOK,
            worker_type="archiveresult",
            pwd=f"/tmp/not-an-archivebox-child/{crawl.id}/title",
            cmd=["python", "--version"],
            status=Process.StatusChoices.EXITED,
            retry_at=None,
            exit_code=0,
            ended_at=timezone.now(),
        )

        recovered = recover_orchestrator_state()

        crawl.refresh_from_db()
        assert "stale_active_crawls_unlocked" not in recovered
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at == old

    def test_recovery_does_not_crash_on_invalid_utf8_process_logs(self, tmp_path):

        runtime_dir = tmp_path / "https_example_com" / ".hooks" / "on_Snapshot__01_title.py"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "stdout.log").write_bytes(b"\\xff\\xfe\\xfa")
        process = Process.objects.create(
            machine=Machine.current(refresh=True),
            iface=NetworkInterface.current(refresh=True),
            process_type=Process.TypeChoices.HOOK,
            worker_type="archiveresult",
            pwd=str(tmp_path / "https_example_com"),
            cmd=["on_Snapshot__01_title.py"],
            status=Process.StatusChoices.RUNNING,
            retry_at=None,
            pid=999999,
            started_at=timezone.now() - timedelta(hours=1),
            timeout=1,
        )

        recover_orchestrator_state()

        process.refresh_from_db()
        assert process.status == Process.StatusChoices.EXITED
