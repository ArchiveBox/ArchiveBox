"""Result lifecycle checks using shipped hooks, real processes, and DB rows."""

import os
import signal
import subprocess
import threading
import time

import pytest
from werkzeug import Response

from archivebox.core.models import ArchiveResult
from archivebox.tests.conftest import cli_env, run_archivebox_cmd
from archivebox.tests.test_archive_result_service import _run_shipped_snapshot_hook
from archivebox.tests.test_orm_helpers import use_archivebox_db


pytestmark = pytest.mark.django_db(transaction=True)


def test_cancelled_hook_discards_result_without_deleting_partial_files(snapshot, cached_abxpkg_lib_dir, httpserver):
    receiving = threading.Event()
    release = threading.Event()

    def stream(_request):
        def body():
            receiving.set()
            yield b"partial capture\n"
            release.wait(60)
            yield b"finished\n"

        return Response(body(), content_type="text/plain")

    httpserver.expect_request("/capture").respond_with_handler(stream)
    snapshot.url = httpserver.url_for("/capture")
    snapshot.save(update_fields=["url"])
    partial = snapshot.output_dir / "wget" / "partial.html"
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_text("partial capture from interrupted attempt")
    try:
        process, result = _run_shipped_snapshot_hook(
            snapshot,
            plugin="wget",
            hook_name="on_Snapshot__35_wget.finite.bg.py",
            lib_dir=cached_abxpkg_lib_dir,
            cancel_when=receiving,
            expected_exit_codes=(130,),
        )
    finally:
        release.set()
    # Process.status records OS liveness; its exit code and ArchiveResult carry
    # failure. A terminated Process is "exited", not an ArchiveResult status.
    assert process.status == "exited"
    assert process.exit_code == 130
    assert result is None
    assert not ArchiveResult.objects.filter(snapshot=snapshot, plugin="wget").exists()
    assert partial.read_text() == "partial capture from interrupted attempt"
    # A later run uses the same real hook and snapshot, with no failed row to
    # reset or delete. The completed response now produces a successful result.
    retry_process, retry_result = _run_shipped_snapshot_hook(
        snapshot,
        plugin="wget",
        hook_name="on_Snapshot__35_wget.finite.bg.py",
        lib_dir=cached_abxpkg_lib_dir,
    )
    assert retry_process.id != process.id
    assert retry_result.status == "succeeded"
    assert ArchiveResult.objects.filter(snapshot=snapshot, plugin="wget").count() == 1


@pytest.mark.parametrize("stop_mode", ["crash", "cancel"])
def test_stopped_hook_reconciles_its_earlier_success(initialized_archive, stop_mode):
    output = initialized_archive / "crash-check.log"
    cli = None
    with output.open("w") as log:
        try:
            cli = run_archivebox_cmd(
                ["add", "--plugins=chrome", "https://example.com"],
                cwd=initialized_archive,
                env=cli_env(CHROME_DELAY_AFTER_LOAD="60", CHROME_TIMEOUT="120", CHROME_HEADLESS="True"),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                wait=False,
                start_new_session=True,
            )
            deadline = time.monotonic() + 90
            successful = None
            while time.monotonic() < deadline:
                with use_archivebox_db(initialized_archive):
                    successful = (
                        ArchiveResult.objects.select_related("process")
                        .filter(
                            hook_name="on_Snapshot__01_chrome_tab.daemon.bg",
                            status="succeeded",
                        )
                        .first()
                    )
                if successful is not None:
                    break
                assert cli.poll() is None, output.read_text()
                time.sleep(0.1)
            assert successful is not None, output.read_text()
            if stop_mode == "cancel":
                cli.send_signal(signal.SIGINT)
                assert cli.wait(timeout=30) == 130
                with use_archivebox_db(initialized_archive):
                    assert not ArchiveResult.objects.filter(pk=successful.pk).exists()
                return
            os.kill(successful.process.pid, signal.SIGKILL)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                with use_archivebox_db(initialized_archive):
                    result = ArchiveResult.objects.select_related("process").get(pk=successful.pk)
                if result.status == "failed" and result.process.exit_code == -signal.SIGKILL:
                    break
                time.sleep(0.1)
            assert result.status == "failed", output.read_text()
            assert result.process.exit_code == -signal.SIGKILL
            assert result.notes
            with use_archivebox_db(initialized_archive):
                assert (
                    ArchiveResult.objects.filter(snapshot_id=result.snapshot_id, plugin="chrome", hook_name=result.hook_name).count() == 1
                )
        finally:
            if cli is not None and cli.poll() is None:
                cli.send_signal(signal.SIGINT)
                cli.wait(timeout=30)
