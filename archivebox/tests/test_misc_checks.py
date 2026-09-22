import os
import signal
import subprocess
import sys
import textwrap

import pytest

from archivebox.core.shutdown_util import foreground_shutdown_signals
from archivebox.core.shutdown_util import raise_if_shutdown_requested
from archivebox.misc.checks import _migration_interrupt_message
from archivebox.misc.checks import is_archivebox_source_root


def test_migration_interrupt_message_prints_resume_command_and_atomic_safety():
    message = _migration_interrupt_message()

    assert "Migration interrupted." in message
    assert "Database migrations are atomic" in message
    assert "no data loss has occurred" in message
    assert "archivebox init" in message


def test_migration_interrupt_message_before_apply_says_no_changes_applied():
    message = _migration_interrupt_message(before_apply=True)

    assert "cancelled before any changes were applied" in message
    assert "archivebox init" in message


def test_source_root_check_treats_inaccessible_probe_paths_as_not_source_root(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'not-archivebox'\n")
    archivebox_dir = tmp_path / "archivebox"
    archivebox_dir.mkdir()
    archivebox_dir.chmod(0)
    try:
        assert is_archivebox_source_root(tmp_path) is False
    finally:
        archivebox_dir.chmod(0o700)


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_migration_interrupt_handler_exits_for_sigint_and_sigterm(sig):
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import signal

                from archivebox.misc.checks import _exit_on_migration_interrupt

                with _exit_on_migration_interrupt():
                    print("READY", flush=True)
                    signal.pause()
                """,
            ),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=os.environ.copy(),
    )
    assert process.stdout is not None
    assert process.stdout.readline() == "READY\n"

    process.send_signal(sig)
    stdout, stderr = process.communicate(timeout=30)

    assert process.returncode == 130, (stdout, stderr)


def test_nested_foreground_signal_state_propagates_to_outer_context():
    with foreground_shutdown_signals(first_signal_message=None) as outer_state:
        try:
            with foreground_shutdown_signals(first_signal_message=None):
                os.kill(os.getpid(), signal.SIGTERM)
        except KeyboardInterrupt:
            pass

        assert outer_state.signal_name == "SIGTERM"
        with pytest.raises(KeyboardInterrupt):
            raise_if_shutdown_requested()
