"""Unlimited export jobs keep their native process lifecycle during cleanup."""

import sys

import pytest

from archivebox.machine.models import Machine, Process
from archivebox.tests.test_machine_models import _spawn_blocked_process

pytestmark = pytest.mark.django_db(transaction=True)


def test_unlimited_export_process_survives_cleanup_until_it_exits():
    child, started_at = _spawn_blocked_process(sys.executable)
    try:
        process = Process.objects.create(
            machine=Machine.current(),
            process_type=Process.TypeChoices.CLI,
            worker_type="site-export",
            status=Process.StatusChoices.RUNNING,
            timeout=0,
            pid=child.pid,
            started_at=started_at,
        )
        assert process.is_running
        Process.cleanup_stale_running()
        process.refresh_from_db()
        assert process.status == Process.StatusChoices.RUNNING
        assert process.exit_code is None
        assert process.is_running
        child.communicate("\n", timeout=5)
        assert child.returncode == 0
        Process.cleanup_stale_running()
        process.refresh_from_db()
        assert process.status == Process.StatusChoices.EXITED
        assert process.exit_code == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_export_status_does_not_load_full_process_logs(admin_client, admin_user, tmp_path):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from archivebox.domains.export_service import export_log_prefix
    from archivebox.machine.models import PROCESS_STDERR_FILE_KEY, PROCESS_STDOUT_FILE_KEY
    from archivebox.tests.conftest import ADMIN_TEST_HOST

    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"
    output = "earlier progress\n" * 5000
    report = '{"destination":"local-test","complete":true,"bytes":23}\n'
    stdout.write_text(output + report)
    stderr.write_text(output + "final diagnostic\n")
    child, started_at = _spawn_blocked_process(sys.executable)
    try:
        process = Process.objects.create(
            machine=Machine.current(),
            process_type=Process.TypeChoices.CLI,
            worker_type="site-export",
            status=Process.StatusChoices.RUNNING,
            timeout=0,
            pid=child.pid,
            started_at=started_at,
            pwd=export_log_prefix(query="", user=admin_user) + "local-test",
            cmd=["archivebox", "--query", "", "--format", "html_zip", "--destination", "local-test", "--user", str(admin_user.pk)],
            env={PROCESS_STDOUT_FILE_KEY: str(stdout), PROCESS_STDERR_FILE_KEY: str(stderr)},
            stdout=output,
            stderr=output,
        )
        child.communicate("\n", timeout=5)
        assert child.returncode == 0
        with CaptureQueriesContext(connection) as queries:
            response = admin_client.get(f"/admin/core/snapshot/export-jobs/{process.pk}/", HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200, response.content
        assert response.json()["result"] == {"destination": "local-test", "complete": True, "bytes": 23}
        assert response.json()["status"] == Process.StatusChoices.EXITED
        process_selects = [q["sql"] for q in queries.captured_queries if q["sql"].startswith("SELECT") and '"machine_process"' in q["sql"]]
        assert process_selects
        assert all('"stdout"' not in sql and '"stderr"' not in sql for sql in process_selects)
        process.refresh_from_db()
        assert len(process.stdout.encode()) == 65536 and process.stdout.endswith(report)
        assert len(process.stderr.encode()) == 65536 and process.stderr.endswith("final diagnostic\n")
        assert stdout.read_text() == output + report
        assert stderr.read_text() == output + "final diagnostic\n"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
