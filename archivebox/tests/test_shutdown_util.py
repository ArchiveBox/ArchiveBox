import os
import signal
import subprocess
import sys
import textwrap


def _start_signal_process(source: str) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(source)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=os.environ.copy(),
    )
    assert process.stdout is not None
    ready_line = process.stdout.readline()
    if ready_line != "READY\n":
        assert process.stderr is not None
        stderr = process.stderr.read()
        process.wait(timeout=30)
        raise AssertionError(f"signal subprocess exited before readiness: {ready_line!r}\n{stderr}")
    return process


def _signal_and_collect(process: subprocess.Popen[str], sig: signal.Signals) -> tuple[str, str]:
    process.send_signal(sig)
    return process.communicate(timeout=30)


def test_foreground_shutdown_second_signal_exits_immediately():
    process = _start_signal_process(
        """
        import signal

        from archivebox.core.shutdown_util import foreground_shutdown_signals

        with foreground_shutdown_signals(first_signal_message=None) as state:
            print("READY", flush=True)
            try:
                signal.pause()
            except KeyboardInterrupt:
                print(f"FIRST:{state.signal_name}", flush=True)
            signal.pause()
        """,
    )

    process.send_signal(signal.SIGTERM)
    assert process.stdout is not None
    assert process.stdout.readline() == "FIRST:SIGTERM\n"
    stdout, stderr = _signal_and_collect(process, signal.SIGTERM)

    assert process.returncode == 130, (stdout, stderr)


def test_foreground_shutdown_can_request_cooperative_shutdown_without_raising():
    process = _start_signal_process(
        """
        import signal

        from archivebox.core.shutdown_util import foreground_shutdown_signals

        def on_signal(sig):
            print(f"SIGNAL:{sig.name}", flush=True)

        with foreground_shutdown_signals(
            first_signal_message=None,
            on_signal=on_signal,
            raise_on_first_signal=False,
        ):
            print("READY", flush=True)
            signal.pause()
            signal.pause()
        """,
    )

    process.send_signal(signal.SIGTERM)
    assert process.stdout is not None
    assert process.stdout.readline() == "SIGNAL:SIGTERM\n"
    stdout, stderr = _signal_and_collect(process, signal.SIGTERM)

    assert process.returncode == 130, (stdout, stderr)


def test_shutdown_signal_during_child_poll_keeps_child_reapable():
    """Interrupt real child polling at different points without stranding reaping.

    The foreground server polls supervisord while its shutdown handler can
    raise KeyboardInterrupt. Exercise that boundary with actual OS signals and
    children; a killed child must remain waitable after every interruption.
    """
    process = _start_signal_process(
        r"""
        import os
        import signal
        import subprocess
        import sys
        import traceback
        from collections import Counter

        from archivebox.core.shutdown_util import foreground_shutdown_signals, wait_popen_and_kill_children

        print("READY", flush=True)
        interruption_sites = Counter()
        for attempt in range(512):
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            interruption_site = None
            try:
                with foreground_shutdown_signals(first_signal_message=None) as state:
                    try:
                        os.write(sys.stdout.fileno(), b"POLLING\n")
                        while child.poll() is None:
                            pass
                    except KeyboardInterrupt as interruption:
                        assert state.signal_name == "SIGINT"
                        # Exclude the signal handler itself from the location.
                        frame = traceback.extract_tb(interruption.__traceback__)[-2]
                        interruption_site = f"{frame.name}:{frame.lineno}"
                        interruption_sites[interruption_site] += 1
                # The child deliberately remains alive until this unchanged
                # kill-and-reap path asks it to stop.
                wait_popen_and_kill_children(child, [], timeout=0.001, kill_timeout=1.0)
                assert child.returncode == -signal.SIGKILL, (attempt, child.returncode)
            except BaseException as error:
                error.add_note(f"Interrupted child polling iteration: {attempt}, at {interruption_site}")
                raise
            finally:
                # Cleanup must also work if the assertion exposes a broken
                # Popen wait; preserve that failure while reaping the real PID.
                if child.returncode is None:
                    try:
                        os.kill(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        os.waitpid(child.pid, 0)
                    except ChildProcessError:
                        pass
        print(f"Interrupt locations: {dict(interruption_sites)}", file=sys.stderr, flush=True)
        print("REAPED:512", flush=True)
        """,
    )

    try:
        # An external sender does not contend for the polling interpreter's
        # GIL. A Timer thread can bias delivery toward waitpid's GIL release,
        # missing other interruption points reached by real CLI Ctrl+C.
        assert process.stdout is not None
        sent = 0
        while sent < 512 and process.stdout.readline() == "POLLING\n":
            process.send_signal(signal.SIGINT)
            sent += 1
        stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert process.returncode == 0, (stdout, stderr)
    assert sent == 512, (sent, stdout, stderr)
    assert stdout == "REAPED:512\n", (stdout, stderr)
    print(stderr)


def test_daemon_runner_signal_exit_is_unexpected_for_supervisor():
    process = _start_signal_process(
        """
        import signal

        from archivebox.cli.archivebox_run import _exit_daemon_runner_on_signal

        signal.signal(signal.SIGTERM, lambda signum, _frame: _exit_daemon_runner_on_signal(signal.Signals(signum)))
        print("READY", flush=True)
        signal.pause()
        """,
    )

    stdout, stderr = _signal_and_collect(process, signal.SIGTERM)

    assert process.returncode == 143, (stdout, stderr)


def test_crawl_runner_daemon_signal_exits_before_async_cleanup():
    process = _start_signal_process(
        """
        import os
        import signal
        import uuid

        import django

        django.setup()

        from archivebox.crawls.models import Crawl
        from archivebox.core.shutdown_util import foreground_shutdown_signals
        from archivebox.services.runner import CrawlRunner

        runner = CrawlRunner(
            Crawl(urls="https://example.com", created_by_id=uuid.uuid4()),
            show_progress=False,
        )
        os.environ["ARCHIVEBOX_RUNNER_DAEMON"] = "1"
        with foreground_shutdown_signals(
            first_signal_message=None,
            on_signal=runner._request_abort_from_signal,
            raise_on_first_signal=False,
        ):
            print("READY", flush=True)
            signal.pause()
        """,
    )

    stdout, stderr = _signal_and_collect(process, signal.SIGTERM)

    assert process.returncode == 143, (stdout, stderr)
