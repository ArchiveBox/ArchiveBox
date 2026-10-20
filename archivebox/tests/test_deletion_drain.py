"""The scheduled filesystem job drains pages without retrying failures in a loop."""

import json
import textwrap
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
def test_scheduled_deletion_drains_past_failed_first_page(initialized_archive):
    from archivebox.core.models import Snapshot

    port = get_free_port()
    env = cli_env(server=True, port=port, disable_extractors=True)
    prepared = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            textwrap.dedent("""
                import json
                from archivebox.base_models.models import get_or_create_system_user_pk
                from archivebox.core.models import Snapshot
                from archivebox.crawls.models import Crawl

                crawl = Crawl.objects.create(
                    urls='https://archivebox.io/tests/deletion',
                    created_by_id=get_or_create_system_user_pk(), status='sealed',
                )
                blocked = Snapshot.objects.create(url=crawl.urls, crawl=crawl, status='deleting')
                path = blocked.output_dir
                path.mkdir(parents=True)
                (path / 'saved.txt').write_text('keep until deletion succeeds')
                path.chmod(0o500)
                for index in range(100):
                    Snapshot.objects.create(
                        url=f'https://archivebox.io/tests/deletion/{index}',
                        crawl=crawl, status='deleting',
                    )
                print(json.dumps({'blocked': str(blocked.pk), 'crawl': str(crawl.pk), 'path': str(path)}))
            """),
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
        server = start_archivebox_server(initialized_archive, port=port, env=env, log_name="delete-drain-server.log")
        wait_for_log(worker_log, "PermissionError", timeout=30)
        deadline = time.monotonic() + 30
        with use_archivebox_db(initialized_archive):
            while Snapshot.objects.filter(crawl_id=fixture["crawl"]).exclude(pk=fixture["blocked"]).exists():
                assert server.poll() is None
                assert time.monotonic() < deadline, worker_log.read_text()
                time.sleep(0.1)
            assert Snapshot.objects.filter(pk=fixture["blocked"], status="deleting").exists()
        assert (protected / "saved.txt").read_text() == "keep until deletion succeeds"
        assert worker_log.read_text().count(f"Snapshot {fixture['blocked']} file deletion failed") == 1
    finally:
        protected.chmod(0o700)
        if server is not None:
            stop_archivebox_process(server)
        kill_processes_for_data_dir(initialized_archive)
