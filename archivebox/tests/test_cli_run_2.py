"""
Tests for archivebox run CLI command.

Tests cover:
- run with stdin JSONL (Crawl, Snapshot, ArchiveResult)
- create-or-update behavior (records with/without id)
- pass-through output (for chaining)
"""

import subprocess

import pytest

from archivebox.tests.conftest import (
    cleanup_process_group,
    cli_env,
    parse_jsonl_output,
    pid_is_alive,
    run_archivebox_cmd,
)

from .test_cli_run_1 import (
    RUN_TEST_ENV as RUN_TEST_ENV,
    _install_real_chrome_for_test as _install_real_chrome_for_test,
)


@pytest.mark.django_db
class TestRecoverOrchestratorState:
    def test_recover_orchestrator_state_unlocks_started_crawl_with_pending_snapshot(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

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
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_crawl

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
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

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
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

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
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

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
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

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
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot
        from archivebox.workers.models import RETRY_AT_MAX

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
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot
        from archivebox.workers.models import RETRY_AT_MAX

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
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

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
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

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
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

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
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.machine.models import Machine, NetworkInterface, Process

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
                machine=Machine.current(),
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
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.workers.models import RETRY_AT_MAX

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
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

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
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

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

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

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
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

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
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

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
        from archivebox.core.models import ArchiveResult
        from archivebox.tests.test_orm_helpers import use_archivebox_db

        env = cli_env(disable_extractors=True)
        env.update(
            {
                "SAVE_TITLE": "false",
                "TIMEOUT": "60",
                "CHROME_TIMEOUT": "30",
            },
        )
        _install_real_chrome_for_test(initialized_archive, env, isolation=chrome_isolation)

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
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

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
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

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
