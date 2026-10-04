"""Exercise queued deletion in the existing runner with a real server."""

import json
import textwrap
import time
from pathlib import Path

import pytest

from archivebox.tests.conftest import (
    cli_env,
    get_free_port,
    kill_processes_for_data_dir,
    resolve_abxpkg_chrome_env,
    run_archivebox_cmd,
    start_archivebox_server,
    stop_archivebox_process,
    wait_for_log,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("restart", [False, True])
def test_runner_retries_failed_deletion_without_blocking_captures(initialized_archive, recursive_test_site, restart):
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
    # Measure captures while deletion retries, not a cold browser installation.
    # Without setup, only the first case spends its capture deadline installing
    # Chrome; later cases silently benefit from the shared binary cache.
    env.update(resolve_abxpkg_chrome_env(Path(env["ABXPKG_LIB_DIR"]), env))
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
    worker_log = initialized_archive / "logs" / "worker_runner.log"
    server = None
    try:
        server = start_archivebox_server(initialized_archive, port=port, env=env, log_name="delete-worker-server.log")
        wait_for_log(worker_log, "PermissionError", timeout=30)
        with use_archivebox_db(initialized_archive):
            assert Process.objects.filter(worker_type="worker_runner", status="running").exists()
            assert not Process.objects.filter(worker_type="worker_snapshot_delete").exists()
            assert Snapshot.objects.filter(pk=fixture["id"], status="deleting").exists()
            assert ArchiveResult.objects.filter(snapshot_id=fixture["id"]).exists()
        assert (protected / "index.html").is_file()
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
        if restart:
            stop_archivebox_process(server)
            server = None
        protected.chmod(0o700)
        if restart:
            server = start_archivebox_server(initialized_archive, port=port, env=env, log_name="delete-restarted-server.log")
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
        if server is not None:
            stop_archivebox_process(server)
        kill_processes_for_data_dir(initialized_archive)


def test_deletion_releases_database_before_filesystem_io(initialized_archive):
    result = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            textwrap.dedent("""
                import json
                import sqlite3
                import sys
                from pathlib import Path
                from django.db import connection
                from archivebox.base_models.models import get_or_create_system_user_pk
                from archivebox.core.models import ArchiveResult, Snapshot
                from archivebox.crawls.models import Crawl
                from archivebox.services.runner import run_pending_crawls

                # DELETE mode exposes both read-cursor and transaction locks.
                with connection.cursor() as cursor:
                    cursor.execute('PRAGMA journal_mode=DELETE')
                    assert cursor.fetchone()[0] == 'delete'
                crawl = Crawl.objects.create(
                    urls='https://example.com/delete',
                    created_by_id=get_or_create_system_user_pk(), status='sealed',
                )
                paths = set()
                snapshot_ids = []
                for i in range(2):
                    snapshot = Snapshot.objects.create(url=f'https://example.com/delete/{i}', crawl=crawl, status='deleting')
                    path = snapshot.output_dir
                    path.mkdir(parents=True, exist_ok=True)
                    (path / 'saved.html').write_text('real saved output')
                    ArchiveResult.objects.create(snapshot=snapshot, plugin='wget', status='succeeded')
                    paths.add(str(path))
                    snapshot_ids.append(snapshot.pk)
                checked = set()

                def inspect_filesystem_operation(event, args):
                    if event != 'shutil.rmtree' or str(args[0]) not in paths:
                        return
                    assert not connection.in_atomic_block
                    # Observe the real rmtree call without replacing it. An
                    # independent writer must acquire its lock immediately.
                    writer = sqlite3.connect(connection.settings_dict['NAME'], timeout=0, isolation_level=None)
                    try:
                        writer.execute('BEGIN EXCLUSIVE')
                        writer.execute('UPDATE crawls_crawl SET notes=? WHERE id=?', ('concurrent write succeeded', crawl.pk.hex))
                        writer.execute('COMMIT')
                    finally:
                        writer.close()
                    checked.add(str(args[0]))

                sys.addaudithook(inspect_filesystem_operation)
                run_pending_crawls(maintenance_only=True)
                assert checked == paths
                assert not Snapshot.objects.filter(crawl=crawl).exists()
                assert not ArchiveResult.objects.filter(snapshot_id__in=snapshot_ids).exists()
                assert all(not Path(path).exists() for path in paths)
                crawl.refresh_from_db()
                assert crawl.notes == 'concurrent write succeeded'
                print(json.dumps({'verified_deletions': len(checked)}))
            """),
        ],
        cwd=initialized_archive,
        env=cli_env(disable_extractors=True),
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {"verified_deletions": 2}
