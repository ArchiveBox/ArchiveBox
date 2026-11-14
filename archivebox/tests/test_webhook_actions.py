"""Real webhook actions, subprocess IO, native updates and admin-visible logs."""

import json
import shlex

import pytest
from django.core.exceptions import ValidationError

pytestmark = pytest.mark.django_db(transaction=True)


def make_hook(admin_user, actions, **kwargs):
    from archivebox.api.models import OutboundWebhook

    hook = OutboundWebhook(
        name=f"Action sequence {admin_user.pk}",
        created_by=admin_user,
        ref="archivebox.core.models.Snapshot",
        signal="BEFORE_CAPTURE",
        actions=actions,
        **kwargs,
    )
    hook.full_clean()
    hook.save()
    return hook


def make_snapshot(admin_user):
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot

    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    return Snapshot.objects.create(url="https://news.ycombinator.com/", crawl=crawl, title="Hacker News")


def action_processes(hook):
    from archivebox.machine.models import Process

    return list(Process.objects.filter(worker_type="webhook", env__ARCHIVEBOX_WEBHOOK_ID=str(hook.pk)).order_by("created_at", "pk"))


def test_python_and_shell_receive_full_input_and_ordered_arguments(admin_user, tmp_path):
    from archivebox.api.webhook_events import emit_event

    python_result, shell_result, shell_args = (tmp_path / name for name in ("python.json", "shell.json", "args.txt"))
    hook = make_hook(
        admin_user,
        [
            {
                "type": "python",
                "code": f"import json, sys\nfrom pathlib import Path\ndata=json.load(sys.stdin)\nPath({str(python_result)!r}).write_text(json.dumps([sys.argv[1:],data]))\nprint(data['title'])",
            },
            {
                "type": "shell",
                "command": f"set -eu\ncat > {shlex.quote(str(shell_result))}\nprintf '%s\\n' \"$@\" > {shlex.quote(str(shell_args))}\nprintf 'done\\n'",
            },
        ],
    )
    snapshot = make_snapshot(admin_user)
    # Larger than a pipe buffer: communicate must drain input without blocking.
    payload_text = "serialized event input " * 6000
    emit_event(snapshot, "BEFORE_CAPTURE", notes=payload_text)
    arguments, payload = json.loads(python_result.read_text())
    assert arguments == [str(snapshot.pk), "core.Snapshot", "BEFORE_CAPTURE"]
    assert payload["url"] == snapshot.url and payload["title"] == snapshot.title
    assert payload["notes"] == payload_text
    assert json.loads(shell_result.read_text()) == payload
    assert shell_args.read_text().splitlines() == arguments
    processes = action_processes(hook)
    assert len(processes) == 2
    assert all(process.status == "exited" and process.exit_code == 0 for process in processes)
    assert processes[0].stdout_file.read_text().strip() == "Hacker News"
    assert processes[1].stdout_file.read_text().strip() == "done"
    assert all(process.started_at and process.ended_at and process.pid for process in processes)
    hook.refresh_from_db()
    assert hook.last_success and not hook.last_failure


def test_failed_action_logs_and_stop_sequence_are_visible_in_admin(admin_user, admin_client, tmp_path, caplog):
    from archivebox.api.webhook_events import emit_event

    marker = tmp_path / "continued.txt"
    hook = make_hook(
        admin_user,
        [
            {"type": "python", "code": "import sys\nprint('action output')\nprint('action failure', file=sys.stderr)\nsys.exit(7)"},
            {"type": "shell", "command": f"printf continued > {shlex.quote(str(marker))}"},
        ],
        stop_on_failure=True,
    )
    snapshot = make_snapshot(admin_user)
    with pytest.raises(RuntimeError, match="BEFORE_CAPTURE webhook failed"):
        emit_event(snapshot, "BEFORE_CAPTURE")
    assert not marker.exists()
    failed = action_processes(hook)[0]
    assert failed.exit_code == 7 and failed.stdout.strip() == "action output"
    assert "action failure" in failed.stderr_file.read_text()
    assert str(failed.pk) in caplog.text and str(hook.pk) in caplog.text
    response = admin_client.get(f"/admin/machine/process/{failed.pk}/change/", HTTP_HOST="admin.archivebox.localhost:5797")
    assert response.status_code == 200
    assert b"action failure" in response.content and b"action output" in response.content
    hook.refresh_from_db()
    assert hook.last_failure and str(failed.pk) in hook.last_response
    hook.stop_on_failure = False
    hook.save(update_fields=["stop_on_failure"])
    with pytest.raises(RuntimeError, match="BEFORE_CAPTURE webhook failed"):
        emit_event(snapshot, "BEFORE_CAPTURE")
    assert marker.read_text() == "continued"
    assert [process.exit_code for process in action_processes(hook)] == [7, 7, 0]


def test_actions_use_native_capture_settings_tags_and_folder(admin_user):
    from archivebox.api.webhook_events import emit_event
    from archivebox.core.models import Folder
    from archivebox.plugins.discovery import get_enabled_plugins
    from archivebox.config.common import get_config

    folder = Folder.objects.create(name="Webhook destination", created_by=admin_user)
    hook = make_hook(
        admin_user,
        [
            {"type": "disable_plugins", "disable_plugins": ["ytdlp"]},
            {"type": "config_overrides", "config_overrides": {"YTDLP_MAX_SIZE": "1256m"}},
            {"type": "add_tags", "add_tags": "News, Reviewed"},
            {"type": "remove_tags", "remove_tags": "reviewed"},
            {"type": "folder", "folder_id": str(folder.pk)},
            {"type": "permissions", "permissions": "public"},
        ],
    )
    snapshot = make_snapshot(admin_user)
    emit_event(snapshot, "BEFORE_CAPTURE")
    snapshot.refresh_from_db()
    assert "ytdlp" not in get_enabled_plugins(config=get_config(crawl=snapshot.crawl, snapshot=snapshot))
    assert snapshot.config["YTDLP_MAX_SIZE"] == "1256m"
    assert list(snapshot.tags.values_list("name", flat=True)) == ["News"]
    assert snapshot.folder_id == folder.pk
    assert snapshot.permissions == "public"
    assert len(action_processes(hook)) == 6
    assert all(process.exit_code == 0 for process in action_processes(hook))


def test_capture_actions_refuse_to_relabel_saved_capture_config(admin_user):
    from archivebox.api.webhook_events import emit_event

    hook = make_hook(admin_user, [{"type": "disable_plugins", "disable_plugins": ["ytdlp"]}])
    snapshot = make_snapshot(admin_user)
    snapshot.status = "sealed"
    snapshot.save(update_fields=["status"])
    original = dict(snapshot.config)
    with pytest.raises(RuntimeError, match="BEFORE_CAPTURE webhook failed"):
        emit_event(snapshot, "BEFORE_CAPTURE")
    snapshot.refresh_from_db()
    assert snapshot.config == original
    process = action_processes(hook)[0]
    assert process.exit_code == 1 and "before this snapshot starts" in process.stderr
    assert process.started_at and process.ended_at


def test_invalid_action_configuration_rejected(admin_user):
    for action in [
        {"type": "disable_plugins", "disable_plugins": ["not-an-installed-plugin"]},
        {"type": "config_overrides", "config_overrides": {"NOT_A_CONFIG_KEY": True}},
        {"type": "http_request", "endpoint": "file:///etc/passwd"},
        {"type": "python", "code": "import ("},
    ]:
        with pytest.raises(ValidationError):
            make_hook(admin_user, [action])


def test_http_action_calls_actual_archivebox_api_and_logs_response(admin_user, live_server):
    from archivebox.api.models import APIToken
    from archivebox.api.webhook_events import emit_event

    token = APIToken.objects.create(created_by=admin_user)
    hook = make_hook(
        admin_user,
        [
            {
                "type": "http_request",
                "method": "GET",
                "endpoint": f"{live_server.url}/api/v1/core/snapshots",
                "headers": {"Host": "admin.archivebox.localhost:5797"},
            },
        ],
        auth_token=f"Bearer {token.token}",
        keep_last_response=True,
    )
    snapshot = make_snapshot(admin_user)
    emit_event(snapshot, "BEFORE_CAPTURE")
    process = action_processes(hook)[0]
    assert process.exit_code == 0
    response = json.loads(process.stdout)
    assert response["status_code"] == 200
    assert str(snapshot.pk) in response["body"]
    assert token.token not in process.stdout + process.stderr + json.dumps(process.env)


def test_failed_action_in_initialized_collection_appears_in_admin_log_views(initialized_archive):
    from archivebox.tests.conftest import run_archivebox_cmd

    script = """
from pathlib import Path
from django.contrib.auth import get_user_model
from django.test import Client
from archivebox.api.models import OutboundWebhook
from archivebox.api.webhook_events import emit_event
from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.core.settings_logging import ERROR_LOG
from archivebox.machine.models import Process
user = get_user_model().objects.create_superuser(username="webhook-log-test", password="testpassword")
crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=user)
snapshot = Snapshot.objects.create(url="https://news.ycombinator.com/", crawl=crawl)
hook = OutboundWebhook(name="Log integration", created_by=user, ref="archivebox.core.models.Snapshot", signal="UPDATE", actions=[{"type":"python", "code":"raise RuntimeError('webhook log integration failure')"}])
hook.full_clean()
hook.save()
emit_event(snapshot, "UPDATE")
process = Process.objects.get(worker_type="webhook", env__ARCHIVEBOX_WEBHOOK_ID=str(hook.pk))
assert process.exit_code == 1
assert Path(ERROR_LOG).name == "errors.log"
assert str(process.pk) in Path(ERROR_LOG).read_text()
client = Client()
client.force_login(user)
response = client.get("/admin/environment/logs/", HTTP_HOST="admin.archivebox.localhost:5797")
assert response.status_code == 200, response.status_code
assert b"errors.log" in response.content
response = client.get("/admin/environment/logs/errors.log/", HTTP_HOST="admin.archivebox.localhost:5797")
assert response.status_code == 200, response.status_code
assert str(process.pk).encode() in response.content
print("webhook failure appears in existing admin log views")
"""
    result = run_archivebox_cmd(["manage", "shell", "-c", script], cwd=initialized_archive)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "webhook failure appears in existing admin log views" in result.stdout


def test_process_stdin_timeout_reaps_the_child(tmp_path):
    import sys
    from archivebox.machine.models import Machine, Process

    process = Process.objects.create(
        machine=Machine.current(),
        process_type="hook",
        worker_type="webhook",
        pwd=str(tmp_path),
        cmd=[sys.executable, "-c", "import time; time.sleep(60)"],
        timeout=1,
    )
    process.launch(stdin=b"x" * 200000)
    assert process.exit_code == 137
    assert process.status == "exited" and process.ended_at
    assert not process.is_alive()


def test_self_api_action_does_not_recurse_and_unsigned_marker_cannot_suppress(admin_user, live_server):
    import httpx
    from archivebox.api.models import APIToken
    from archivebox.api.webhook_events import emit_event
    from archivebox.config.common import get_config
    from archivebox.machine.models import Machine

    machine = Machine.current()
    previous_config = dict(machine.config or {})
    machine.config = {**previous_config, "BASE_URL": live_server.url}
    machine.save(update_fields=["config"])
    try:
        assert get_config().BASE_URL == live_server.url
        token = APIToken.objects.create(created_by=admin_user)
        snapshot = make_snapshot(admin_user)
        hook = make_hook(
            admin_user,
            [
                {
                    "type": "http_request",
                    "method": "PATCH",
                    "endpoint": "/api/v1/core/snapshot/{{ object.id }}",
                    "headers": {"Host": live_server.url.split("//", 1)[1], "x-archivebox-webhook": "unsigned"},
                    "body": {"tags": ["self-api-action"]},
                },
            ],
            auth_token=f"Bearer {token.token}",
        )
        hook.signal = "UPDATE"
        hook.save(update_fields=["signal"])
        emit_event(snapshot, "UPDATE")
        processes = action_processes(hook)
        assert len(processes) == 1 and processes[0].exit_code == 0
        assert snapshot.tags.filter(name="self-api-action").exists()
        response = httpx.patch(
            f"{live_server.url}/api/v1/core/snapshot/{snapshot.pk}",
            json={},
            headers={
                "Host": live_server.url.split("//", 1)[1],
                "Authorization": f"Bearer {token.token}",
                "X-ArchiveBox-Webhook": "unsigned",
            },
        )
        assert response.status_code == 200, response.text
        processes = action_processes(hook)
        assert len(processes) == 2 and all(process.exit_code == 0 for process in processes)
    finally:
        machine.config = previous_config
        machine.save(update_fields=["config"])


def test_child_python_django_save_does_not_recurse(initialized_archive):
    from archivebox.tests.conftest import run_archivebox_cmd

    script = """
from django.contrib.auth import get_user_model
from archivebox.api.models import OutboundWebhook
from archivebox.api.webhook_events import emit_event
from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process
user = get_user_model().objects.create_superuser(username="webhook-child-test", password="testpassword")
crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=user)
snapshot = Snapshot.objects.create(url="https://news.ycombinator.com/", crawl=crawl)
code = "import sys; from archivebox.config.django import setup_django; setup_django(); from archivebox.core.models import Snapshot; obj=Snapshot.objects.get(pk=sys.argv[1]); obj.title='child saved'; obj.save(update_fields=['title']); print(obj.title)"
hook = OutboundWebhook(name="Child update", created_by=user, ref="archivebox.core.models.Snapshot", signal="UPDATE", actions=[{"type":"python", "code":code}])
hook.full_clean()
hook.save()
emit_event(snapshot, "UPDATE")
snapshot.refresh_from_db()
assert snapshot.title == "child saved"
processes = list(Process.objects.filter(worker_type="webhook", env__ARCHIVEBOX_WEBHOOK_ID=str(hook.pk)))
assert len(processes) == 1, len(processes)
assert processes[0].exit_code == 0, processes[0].stderr
print("child Django mutation did not recurse")
"""
    result = run_archivebox_cmd(["manage", "shell", "-c", script], cwd=initialized_archive)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "child Django mutation did not recurse" in result.stdout


def test_blocking_native_actions_run_under_lifecycle_lock_and_self_api_fails_fast(admin_user):
    from archivebox.api.webhook_events import emit_event
    from archivebox.crawls.locks import crawl_lifecycle_lock

    snapshot = make_snapshot(admin_user)
    hook = make_hook(admin_user, [{"type": "disable_plugins", "disable_plugins": ["ytdlp"]}])
    with crawl_lifecycle_lock(str(snapshot.crawl_id)):
        emit_event(snapshot, "BEFORE_CAPTURE")
        snapshot.refresh_from_db()
        assert "ytdlp" not in snapshot.config["PLUGINS"]
        assert action_processes(hook)[0].exit_code == 0

        hook.actions = [
            {
                "type": "http_request",
                "method": "PATCH",
                "endpoint": "/api/v1/core/snapshot/{{ object.id }}",
                "body": {"tags": ["must-not-run"]},
            },
        ]
        hook.save(update_fields=["actions"])
        with pytest.raises(RuntimeError, match="BEFORE_CAPTURE webhook failed"):
            emit_event(snapshot, "BEFORE_CAPTURE")
        failed = action_processes(hook)[1]
        assert failed.exit_code == 1
        assert "cannot call a mutating ArchiveBox API while a lifecycle lock is held" in failed.stderr_file.read_text()
        assert not snapshot.tags.filter(name="must-not-run").exists()


def test_post_event_sequence_waits_for_outer_lock_across_sync_to_async(admin_user, tmp_path):
    from asgiref.sync import async_to_sync, sync_to_async
    from archivebox.api.webhook_events import emit_event
    from archivebox.crawls.locks import crawl_lifecycle_lock, binary_lifecycle_lock

    snapshot = make_snapshot(admin_user)
    marker = tmp_path / "released.txt"
    hook = make_hook(
        admin_user,
        [{"type": "add_tags", "add_tags": "after-release"}, {"type": "shell", "command": f"printf released > {shlex.quote(str(marker))}"}],
    )
    hook.signal = "UPDATE"
    hook.save(update_fields=["signal"])

    async def update_from_worker():
        await sync_to_async(emit_event)(snapshot, "UPDATE")

    with crawl_lifecycle_lock(str(snapshot.crawl_id)):
        with binary_lifecycle_lock(str(snapshot.pk)):
            async_to_sync(update_from_worker)()
            assert not action_processes(hook)
        assert not action_processes(hook)
        assert not snapshot.tags.filter(name="after-release").exists()
        assert not marker.exists()
    assert marker.read_text() == "released"
    assert snapshot.tags.filter(name="after-release").exists()
    assert [process.exit_code for process in action_processes(hook)] == [0, 0]
