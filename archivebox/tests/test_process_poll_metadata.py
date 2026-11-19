"""Exit polling must not restore stale foreign keys from a loaded row."""

import subprocess
import sys
from datetime import timedelta

import pytest
from django.utils import timezone
from django.db import connection

from archivebox.machine.models import Binary, Machine, Process


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("relation", ["binary", "parent"])
def test_poll_preserves_deleted_relation_and_concurrent_metadata(tmp_path, relation):
    machine = Machine.current()
    with (tmp_path / "stdout.log").open("w") as stdout, (tmp_path / "stderr.log").open("w") as stderr:
        child = subprocess.Popen(
            [sys.executable, "-c", "import sys; print('finished'); print('diagnostic', file=sys.stderr)"],
            stdout=stdout,
            stderr=stderr,
        )
        assert child.wait(timeout=10) == 0
    related = (
        Binary.objects.create(machine=machine, name="python")
        if relation == "binary"
        else Process.objects.create(machine=machine, status="exited")
    )
    process = Process.objects.create(
        machine=machine,
        process_type="binary",
        status="running",
        pid=child.pid,
        pwd=str(tmp_path),
        env={"DELETE_AFTER": "100y"},
        **{relation: related},
    )
    loaded = Process.objects.get(pk=process.pk)
    related.delete()
    created_at = timezone.now() - timedelta(days=3)
    Process.objects.filter(pk=process.pk).update(created_at=created_at, cmd=["retained-command"])
    assert Process.objects.get(pk=process.pk).__dict__[f"{relation}_id"] is None
    connection.check_constraints()
    assert loaded.poll() is not None
    process.refresh_from_db()
    assert process.status == "exited"
    assert process.__dict__[f"{relation}_id"] is None
    assert process.created_at == created_at
    assert process.cmd == ["retained-command"]
    assert process.stdout == "finished\n"
    assert process.stderr == "diagnostic\n"
    assert process.ended_at is not None
    assert process.delete_at is not None
    connection.check_constraints()
    assert Process.cleanup_stale_running(machine=machine) == 0
