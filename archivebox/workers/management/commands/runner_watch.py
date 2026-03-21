from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Watch the runserver autoreload PID file and restart the background runner on reloads."

    def add_arguments(self, parser):
        parser.add_argument(
            "--pidfile",
            default=None,
            help="Path to runserver pidfile to watch",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=1.0,
            help="Polling interval in seconds",
        )

    def handle(self, *args, **kwargs):
        import os
        import subprocess
        import sys
        import time

        from archivebox.config.common import STORAGE_CONFIG
        from archivebox.machine.models import Machine, Process

        pidfile = kwargs.get("pidfile") or os.environ.get("ARCHIVEBOX_RUNSERVER_PIDFILE")
        if not pidfile:
            pidfile = str(STORAGE_CONFIG.TMP_DIR / "runserver.pid")

        interval = max(0.2, float(kwargs.get("interval", 1.0)))
        last_pid = None
        runner_proc: subprocess.Popen[bytes] | None = None

        def restart_runner() -> None:
            nonlocal runner_proc

            Process.cleanup_stale_running()
            machine = Machine.current()

            running = Process.objects.filter(
                machine=machine,
                status=Process.StatusChoices.RUNNING,
                process_type__in=[
                    Process.TypeChoices.ORCHESTRATOR,
                    Process.TypeChoices.HOOK,
                    Process.TypeChoices.BINARY,
                ],
            )
            for proc in running:
                try:
                    proc.kill_tree(graceful_timeout=0.5)
                except Exception:
                    continue

            if runner_proc and runner_proc.poll() is None:
                try:
                    runner_proc.terminate()
                    runner_proc.wait(timeout=2.0)
                except Exception:
                    try:
                        runner_proc.kill()
                    except Exception:
                        pass

            runner_proc = subprocess.Popen(
                [sys.executable, '-m', 'archivebox', 'run', '--daemon'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

        def runner_running() -> bool:
            return Process.objects.filter(
                machine=Machine.current(),
                status=Process.StatusChoices.RUNNING,
                process_type=Process.TypeChoices.ORCHESTRATOR,
            ).exists()

        while True:
            try:
                if os.path.exists(pidfile):
                    with open(pidfile, "r") as handle:
                        pid = handle.read().strip() or None
                else:
                    pid = None

                if pid and pid != last_pid:
                    restart_runner()
                    last_pid = pid
                elif not runner_running():
                    restart_runner()
            except Exception:
                pass

            time.sleep(interval)
