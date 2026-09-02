"""Machine, binary, and process admin UI tests."""

import uuid
import asyncio
import os
from importlib.resources import files
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils import timezone

from archivebox.tests.conftest import ADMIN_TEST_HOST
from archivebox.tests.conftest import install_real_binary
from archivebox.tests.conftest import resolve_abxpkg_binary_env

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def real_exited_hook_process(tmp_path):
    from archivebox.tests.conftest import run_test_hook

    snap_dir = tmp_path / "snapshot"
    output_dir = snap_dir / "hashes"
    output_dir.mkdir(parents=True)
    (snap_dir / "source.txt").write_text("real admin hook input", encoding="utf-8")
    hook_path = Path(str(files("abx_plugins.plugins.hashes").joinpath("on_Snapshot__93_hashes.py")))
    process = run_test_hook(
        hook_path,
        output_dir,
        config={"ABXPKG_LIB_DIR": str(tmp_path / "lib"), "SNAP_DIR": str(snap_dir)},
        timeout=30,
        url="https://example.com/admin-hook",
    )
    process.refresh_from_db()
    assert process.exit_code == 0, process.stderr
    assert (output_dir / "hashes.json").is_file()
    return process


@pytest.fixture
def real_projected_hash_result(snapshot, cached_abxpkg_lib_dir):
    from abx_dl.events import ProcessEvent, SnapshotEvent
    from abx_dl.orchestrator import create_bus
    from abx_dl.services.archive_result_service import ArchiveResultService as HookArchiveResultService
    from abx_dl.services.process_service import ProcessService as HookProcessService
    from archivebox.core.models import ArchiveResult
    from archivebox.machine.models import Process
    from archivebox.services.archive_result_service import ArchiveResultService
    from archivebox.services.process_service import ProcessService as PersistedProcessService

    plugin = "hashes"
    hook_name = "on_Snapshot__93_hashes.py"
    hook_path = Path(str(files("abx_plugins.plugins.hashes").joinpath(hook_name)))
    hook_config = hook_path.parent / "config.json"
    binary_env = resolve_abxpkg_binary_env(cached_abxpkg_lib_dir, deps_from=hook_config)
    output_dir = snapshot.output_dir / plugin
    output_dir.mkdir(parents=True, exist_ok=True)
    (snapshot.output_dir / "source.txt").write_text("real admin projection input", encoding="utf-8")
    bus = create_bus(name=f"test_admin_hashes_{snapshot.id}")
    HookProcessService(bus, emit_jsonl=False, interactive_tty=False)
    HookArchiveResultService(bus, emit_jsonl=False)
    PersistedProcessService(bus)
    ArchiveResultService(bus)

    async def run() -> None:
        try:
            snapshot_event = SnapshotEvent(
                url=snapshot.url,
                snapshot_id=str(snapshot.id),
                output_dir=str(snapshot.output_dir),
            )
            await bus.emit(snapshot_event).now()
            await bus.emit(
                ProcessEvent(
                    plugin_name=plugin,
                    hook_name=hook_name,
                    hook_path=str(hook_path),
                    hook_args=[f"--url={snapshot.url}"],
                    env={
                        **binary_env,
                        "ABXPKG_LIB_DIR": str(cached_abxpkg_lib_dir),
                        "SNAP_DIR": str(snapshot.output_dir),
                        "PATH": f"{Path(os.sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
                    },
                    output_dir=str(output_dir),
                    timeout=60,
                    is_background=False,
                    url=snapshot.url,
                    process_type="hook",
                    worker_type="hook",
                    event_parent_id=snapshot_event.event_id,
                ),
            ).now()
            await bus.wait_until_idle()
        finally:
            await bus.destroy(clear=False)

    asyncio.run(run())
    process = Process.objects.filter(pwd=str(output_dir)).order_by("-created_at").first()
    assert process is not None
    process.refresh_from_db()
    assert process.exit_code == 0, (process.stdout, process.stderr)
    result = ArchiveResult.objects.get(snapshot=snapshot, plugin=plugin, hook_name=hook_name)
    return process, result


class TestMachineAdmin:
    def test_binary_change_view_renders(self, client, admin_user, db):
        """Binary admin change form should load without FieldError."""
        from archivebox.machine.models import Machine

        machine = Machine.objects.create(
            guid=f"test-guid-{uuid.uuid4()}",
            hostname="test-host",
            hw_in_docker=False,
            hw_in_vm=False,
            hw_manufacturer="Test",
            hw_product="Test Product",
            hw_uuid=f"test-hw-{uuid.uuid4()}",
            os_arch="x86_64",
            os_family="darwin",
            os_platform="darwin",
            os_release="test",
            os_kernel="test-kernel",
            stats={},
        )
        binary = install_real_binary("python3", machine=machine)

        client.force_login(admin_user)
        url = f"/admin/machine/binary/{binary.pk}/change/"
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert binary.name.encode() in response.content
        assert binary.version.encode() in response.content

    def test_process_change_view_renders_copyable_cmd_env_and_readonly_runtime_fields(
        self,
        client,
        admin_user,
        real_exited_hook_process,
    ):
        from datetime import timedelta

        process = real_exited_hook_process
        process.env.update(
            {
                "ENABLED": True,
                "API_KEY": "super-secret-key",
                "ACCESS_TOKEN": "super-secret-token",
                "SHARED_SECRET": "super-secret-secret",
            },
        )
        process.started_at = timezone.now() - timedelta(seconds=52)
        process.ended_at = timezone.now()
        process.save(update_fields=["env", "started_at", "ended_at"])

        client.force_login(admin_user)
        url = reverse("admin:machine_process_change", args=[process.pk])
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"Kill" in response.content
        assert b"on_Snapshot__93_hashes.py" in response.content
        assert b"ENABLED=True" in response.content
        assert b"ArchiveResult" in response.content
        assert b"52s" in response.content
        assert b"API_KEY=" not in response.content
        assert b"ACCESS_TOKEN=" not in response.content
        assert b"SHARED_SECRET=" not in response.content
        assert b"super-secret-key" not in response.content
        assert b"super-secret-token" not in response.content
        assert b"super-secret-secret" not in response.content
        assert response.content.count(b"data-command=") >= 2
        assert b'name="timeout"' not in response.content
        assert b'name="pid"' not in response.content
        assert b'name="exit_code"' not in response.content
        assert b'name="stdout"' not in response.content
        assert b'name="stderr"' not in response.content
        assert b'name="url"' not in response.content
        assert b'name="started_at"' not in response.content
        assert b'name="ended_at"' not in response.content

    def test_process_kill_object_action_is_post_only(self, admin_client, real_exited_hook_process):
        from archivebox.machine.models import Process

        process = real_exited_hook_process
        action_url = reverse("admin:machine_process_actions", kwargs={"pk": process.pk, "tool": "kill_process"})

        change_response = admin_client.get(reverse("admin:machine_process_change", args=[process.pk]), HTTP_HOST=ADMIN_TEST_HOST)
        assert change_response.status_code == 200
        assert b'<form method="post"' in change_response.content
        assert action_url.encode() in change_response.content

        get_response = admin_client.get(action_url, HTTP_HOST=ADMIN_TEST_HOST)
        assert get_response.status_code == 405

        post_response = admin_client.post(action_url, HTTP_HOST=ADMIN_TEST_HOST)
        assert post_response.status_code == 302
        assert post_response.url == reverse("admin:machine_process_change", args=[process.pk])
        process.refresh_from_db()
        assert process.status == Process.StatusChoices.EXITED

    def test_process_list_view_shows_duration_snapshot_and_crawl_columns(
        self,
        client,
        admin_user,
        snapshot,
        real_projected_hash_result,
    ):
        process, result = real_projected_hash_result

        client.force_login(admin_user)
        response = client.get(reverse("admin:machine_process_changelist"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"Duration" in response.content
        assert b"Snapshot" in response.content
        assert b"Crawl" in response.content
        assert result.status == "succeeded"
        assert process.started_at is not None
        assert process.ended_at is not None
        changelist = response.context["cl"]
        row = next(obj for obj in changelist.result_list if obj.pk == process.pk)

        assert row.archiveresult.snapshot_id == snapshot.id
        assert str(snapshot.id) in str(changelist.model_admin.snapshot_link(row))
        assert str(snapshot.crawl_id) in str(changelist.model_admin.crawl_link(row))
