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
