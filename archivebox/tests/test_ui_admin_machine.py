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


def test_process_list_defers_logs_but_search_detail_and_actions_preserve_them(admin_client, tmp_path):
    import sys
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from archivebox.machine.models import Machine, Process

    processes = []
    for index in range(3):
        process = Process.objects.create(
            machine=Machine.current(),
            pwd=str(tmp_path / str(index)),
            cmd=[
                sys.executable,
                "-c",
                "import hashlib,sys; print(hashlib.sha256(b'out').hexdigest()); print(hashlib.sha256(b'err').hexdigest(), file=sys.stderr)",
            ],
        )
        process.launch()
        process.refresh_from_db()
        assert process.exit_code == 0
        processes.append(process)
    process = processes[0]
    list_url = reverse("admin:machine_process_changelist")
    for params in ({}, {"q": process.stdout.strip()}, {"q": process.stderr.strip()}):
        with CaptureQueriesContext(connection) as queries:
            response = admin_client.get(list_url, params, HTTP_HOST=ADMIN_TEST_HOST)
            assert response.status_code == 200
            rows = list(response.context["cl"].result_list)
            assert {row.pk for row in rows} == {row.pk for row in processes}
            assert all({"stdout", "stderr"} <= row.get_deferred_fields() for row in rows)
        # Rendering must never trigger a deferred-field lookup for each row.
        for query in queries.captured_queries:
            projection = query["sql"].split(" FROM ", 1)[0]
            assert '"machine_process"."stdout"' not in projection
            assert '"machine_process"."stderr"' not in projection
    detail = admin_client.get(reverse("admin:machine_process_change", args=[process.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    assert detail.status_code == 200
    assert process.stdout.strip().encode() in detail.content
    assert process.stderr.strip().encode() in detail.content
    assert not {"stdout", "stderr"} & detail.context["original"].get_deferred_fields()
    # POST action querysets stay unchanged; previewing deletion deletes nothing.
    preview = admin_client.post(list_url, {"action": "delete_selected", "_selected_action": str(process.pk)}, HTTP_HOST=ADMIN_TEST_HOST)
    assert preview.status_code == 200
    assert not {"stdout", "stderr"} & preview.context["queryset"][0].get_deferred_fields()
    assert Process.objects.filter(pk=process.pk).exists()


def test_process_list_defers_crawl_payload_without_refetching_links(admin_client, admin_user, rf, snapshot, tmp_path):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from django.urls import resolve

    from archivebox.core.models import ArchiveResult
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Machine, Process

    machine = Machine.objects.create(
        guid=f"test-guid-{uuid.uuid4()}",
        hostname="test-host",
        hw_manufacturer="Test",
        hw_product="Test Product",
        hw_uuid=f"test-hw-{uuid.uuid4()}",
        os_arch="x86_64",
        os_family="linux",
        os_platform="linux",
        os_release="test",
        os_kernel="test-kernel",
    )
    crawl = snapshot.crawl
    urls = "https://example.com/large-seed\n" * 4096
    config = {**crawl.config, "FIXTURE_CRAWL_CONFIG": "x" * 65536}
    Crawl.objects.filter(pk=crawl.pk).update(urls=urls, config=config)
    process = Process.objects.create(machine=machine, pwd=str(tmp_path), cmd=["test-process"], stdout="test-process-log")
    ArchiveResult.objects.create(snapshot=snapshot, process=process, plugin="hashes", hook_name="test-hash")
    list_url = reverse("admin:machine_process_changelist")
    detail_url = reverse("admin:machine_process_change", args=[process.pk])

    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get(list_url, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert reverse("admin:crawls_crawl_change", args=[crawl.pk]).rstrip("/").encode() in response.content
        row = next(obj for obj in response.context["cl"].result_list if obj.pk == process.pk)
        assert {"urls", "config"} <= row.archiveresult.snapshot.crawl.get_deferred_fields()
    for query in queries.captured_queries:
        projection = query["sql"].split(" FROM ", 1)[0]
        assert '"crawls_crawl"."urls"' not in projection
        assert '"crawls_crawl"."config"' not in projection

    detail = admin_client.get(detail_url, HTTP_HOST=ADMIN_TEST_HOST)
    assert detail.status_code == 200
    assert b"test-process-log" in detail.content
    detail_crawl = detail.context["original"].archiveresult.snapshot.crawl
    assert not detail_crawl.get_deferred_fields()
    assert detail_crawl.urls == urls
    assert detail_crawl.config == config

    search = admin_client.get(list_url, {"q": "test-process-log"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert search.status_code == 200
    assert [row.pk for row in search.context["cl"].result_list] == [process.pk]

    request = rf.post(list_url)
    request.resolver_match = resolve(list_url)
    request.user = admin_user
    action_crawl = response.context["cl"].model_admin.get_queryset(request).get(pk=process.pk).archiveresult.snapshot.crawl
    assert not action_crawl.get_deferred_fields()
    assert action_crawl.urls == urls
    assert action_crawl.config == config


@pytest.mark.parametrize("prewarm_display", [False, True], ids=["cold", "warm"])
def test_machine_edit_reserves_sqlite_writer_before_reading(admin_client, admin_user, prewarm_display):
    import json
    import sqlite3
    from time import perf_counter

    from django.db import connection, transaction
    from django.test.utils import CaptureQueriesContext

    from archivebox.machine.models import Machine

    credential = "synthetic-machine-test-value"
    machine = Machine.from_json({"config": {"KAGI_SEARCH_API_KEY": credential}})
    assert machine is not None
    url = reverse("admin:machine_machine_change", args=[machine.pk])
    previous_mode = getattr(connection, "transaction_mode", None)
    if prewarm_display:
        with CaptureQueriesContext(connection) as get_queries:
            page = admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
        assert page.status_code == 200
        assert credential.encode() not in page.content
        assert not any(query["sql"] == "BEGIN IMMEDIATE" for query in get_queries)

    # Machine admin's ordinary editable model inputs, without warming the grid.
    fields = {
        key: getattr(machine, key)
        for key in (
            "hostname",
            "hw_manufacturer",
            "hw_product",
            "hw_uuid",
            "os_platform",
            "os_family",
            "os_arch",
            "os_kernel",
            "os_release",
            "num_uses_succeeded",
            "num_uses_failed",
        )
    }
    for flag in ("hw_in_docker", "hw_in_vm"):
        if getattr(machine, flag):
            fields[flag] = "on"

    def post(**overrides):
        return admin_client.post(
            url,
            {
                **fields,
                "config": json.dumps({"KAGI_SEARCH_API_KEY": "", "USER_AGENT": "Machine writer test"}),
                "_save": "Save",
                **overrides,
            },
            HTTP_HOST=ADMIN_TEST_HOST,
        )

    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            assert cursor.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        other = sqlite3.connect(connection.settings_dict["NAME"], timeout=0, isolation_level=None)
        competing_writer_results = []
        lock_times = []
        begin = None

        def compete_after_machine_read(execute, sql, params, many, context):
            nonlocal begin
            result = execute(sql, params, many, context)
            if sql == "BEGIN IMMEDIATE":
                begin = perf_counter()
            if (
                not competing_writer_results
                and sql.lstrip().upper().startswith("SELECT")
                and "machine_machine" in sql
                and connection.in_atomic_block
            ):
                if begin is not None:
                    transaction.on_commit(lambda: lock_times.append(perf_counter() - begin))
                # A separate WAL writer must not commit between this request's
                # first read and first write, or SQLite cannot upgrade its snapshot.
                try:
                    other.execute("UPDATE auth_user SET last_name='competing writer' WHERE id=?", (admin_user.pk,))
                except sqlite3.OperationalError as error:
                    assert error.sqlite_errorcode == sqlite3.SQLITE_BUSY
                    competing_writer_results.append("reserved")
                else:
                    competing_writer_results.append("committed")
            return result

        try:
            with connection.execute_wrapper(compete_after_machine_read), CaptureQueriesContext(connection) as queries:
                response = post()
            assert competing_writer_results == ["reserved"]
            assert any(query["sql"] == "BEGIN IMMEDIATE" for query in queries)
            assert not any('FROM "machine_binary"' in query["sql"] for query in queries)
            assert len(lock_times) == 1
            print(f"Machine change SQLite writer held {lock_times[0] * 1000:.1f} ms (display prewarmed: {prewarm_display})")
            assert connection.transaction_mode == previous_mode
            other.execute("UPDATE auth_user SET last_name='competing writer' WHERE id=?", (admin_user.pk,))
        finally:
            other.close()
    else:
        response = post()

    assert response.status_code == 302
    machine.refresh_from_db()
    assert machine.config["KAGI_SEARCH_API_KEY"] == credential
    assert machine.config["USER_AGENT"] == "Machine writer test"

    binary_link_reads = []

    def observe_render_sql(execute, sql, params, many, context):
        if 'FROM "machine_binary"' in sql:
            binary_link_reads.append(connection.in_atomic_block)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(observe_render_sql):
        invalid = post(hostname="")
    assert binary_link_reads and not any(binary_link_reads)
    assert invalid.status_code == 200
    assert "hostname" in invalid.context["adminform"].form.errors
    assert credential.encode() not in invalid.content
    assert getattr(connection, "transaction_mode", None) == previous_mode
