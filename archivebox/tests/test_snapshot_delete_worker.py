"""Exercise filesystem failures and worker isolation with a real server."""

import json
import os
import signal
import time
from pathlib import Path

import pytest

from archivebox.tests.conftest import (
    cli_env,
    get_free_port,
    kill_processes_for_data_dir,
    run_archivebox_cmd,
    start_archivebox_server,
    stop_archivebox_process,
    wait_for_log,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db


@pytest.mark.django_db(transaction=True)
def test_failed_and_paused_deletion_worker_does_not_block_captures(initialized_archive, recursive_test_site):
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Process

    port = get_free_port()
    env = cli_env(
        live=True,
        server=True,
        port=port,
        PLUGINS="title",
        SAVE_TITLE="True",
        SEARCH_BACKEND_ENGINE="ripgrep",
    )
    prepared = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            "import json; from archivebox.crawls.models import Crawl; "
            "from archivebox.core.models import Snapshot, ArchiveResult; "
            "from archivebox.base_models.models import get_or_create_system_user_pk; "
            "c=Crawl.objects.create(urls='https://example.com/delete',created_by_id=get_or_create_system_user_pk(),status='sealed'); "
            "s=Snapshot.objects.create(url='https://example.com/delete',crawl=c,status='deleting'); "
            "p=s.output_dir/'wget'; p.mkdir(parents=True,exist_ok=True); "
            "(p/'index.html').write_text('keep this until cleanup succeeds'); "
            "ArchiveResult.objects.create(snapshot=s,plugin='wget',hook_name='on_Snapshot__06_wget',status='succeeded'); "
            "p.chmod(0o500); print(json.dumps({'id':str(s.pk),'path':str(p)}))",
        ],
        cwd=initialized_archive,
        env=env,
    )
    assert prepared.returncode == 0, prepared.stderr or prepared.stdout
    fixture = json.loads(prepared.stdout.strip().splitlines()[-1])
    protected = Path(fixture["path"])
    worker_log = initialized_archive / "logs" / "worker_snapshot_delete.log"
    server = None
    deletion_pid = None
    try:
        server = start_archivebox_server(initialized_archive, port=port, env=env, log_name="delete-worker-server.log")
        wait_for_log(worker_log, "PermissionError", timeout=30)
        with use_archivebox_db(initialized_archive):
            deletion = Process.objects.get(worker_type="worker_snapshot_delete", status="running")
            runner = Process.objects.get(worker_type="worker_runner", status="running")
            assert deletion.pid != runner.pid
            deletion_pid = deletion.pid
            assert Snapshot.objects.filter(pk=fixture["id"], status="deleting").exists()
            assert ArchiveResult.objects.filter(snapshot_id=fixture["id"]).exists()
        assert (protected / "index.html").is_file()
        # Suspend the actual cleanup process. The scheduler and its real title
        # hook must still finish a new capture without waiting for this worker.
        os.kill(deletion_pid, signal.SIGSTOP)
        added = run_archivebox_cmd(
            ["add", "--bg", "--plugins=title", recursive_test_site["root_url"]],
            cwd=initialized_archive,
            env=env,
        )
        assert added.returncode == 0, added.stderr or added.stdout
        deadline = time.monotonic() + 60
        with use_archivebox_db(initialized_archive):
            while time.monotonic() < deadline:
                captured = Snapshot.objects.filter(url=recursive_test_site["root_url"], status="sealed").first()
                if captured is not None:
                    break
                assert server.poll() is None
                time.sleep(0.1)
            else:
                pytest.fail((initialized_archive / "logs" / "worker_runner.log").read_text()[-12000:])
            result = ArchiveResult.objects.get(snapshot=captured, plugin="title", status="succeeded")
            assert result.output_files
            assert captured.title == "Root"
            assert Snapshot.objects.filter(pk=fixture["id"], status="deleting").exists()
        protected.chmod(0o700)
        os.kill(deletion_pid, signal.SIGCONT)
        deadline = time.monotonic() + 75
        with use_archivebox_db(initialized_archive):
            while Snapshot.objects.filter(pk=fixture["id"]).exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            assert not Snapshot.objects.filter(pk=fixture["id"]).exists(), worker_log.read_text()
            assert not ArchiveResult.objects.filter(snapshot_id=fixture["id"]).exists()
        assert not protected.parent.exists()
    finally:
        if protected.exists():
            protected.chmod(0o700)
        if deletion_pid is not None:
            try:
                os.kill(deletion_pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        if server is not None:
            stop_archivebox_process(server)
        kill_processes_for_data_dir(initialized_archive)
