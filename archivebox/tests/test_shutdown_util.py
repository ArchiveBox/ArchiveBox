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
