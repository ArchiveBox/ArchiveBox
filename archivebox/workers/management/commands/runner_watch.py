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
        import time

        import psutil

        from archivebox.config.common import STORAGE_CONFIG
        from archivebox.machine.models import Machine, Process
        from archivebox.workers.supervisord_util import (
            RUNNER_WORKER,
            get_existing_supervisord_process,
            get_worker,
            start_worker,
            stop_worker,
        )

        pidfile = kwargs.get("pidfile") or os.environ.get("ARCHIVEBOX_RUNSERVER_PIDFILE")
        if not pidfile:
            pidfile = str(STORAGE_CONFIG.TMP_DIR / "runserver.pid")

        interval = max(0.2, float(kwargs.get("interval", 1.0)))
        last_pid = None

        def stop_duplicate_watchers() -> None:
            current_pid = os.getpid()
            for proc in psutil.process_iter(["pid", "cmdline"]):
                if proc.info["pid"] == current_pid:
                    continue
                cmdline = proc.info.get("cmdline") or []
                if not cmdline:
                    continue
                if "runner_watch" not in " ".join(cmdline):
                    continue
                if not any(str(arg) == f"--pidfile={pidfile}" or str(arg) == pidfile for arg in cmdline):
                    continue
                try:
                    proc.terminate()
                    proc.wait(timeout=2.0)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    try:
                        proc.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

        def get_supervisor():
            supervisor = get_existing_supervisord_process()
            if supervisor is None:
                raise RuntimeError("runner_watch requires a running supervisord process")
            return supervisor

        stop_duplicate_watchers()
        start_worker(get_supervisor(), RUNNER_WORKER, lazy=True)

        def restart_runner() -> None:
            Process.cleanup_stale_running()
            Process.cleanup_orphaned_workers()
            machine = Machine.current()

            running = Process.objects.filter(
                machine=machine,
                status=Process.StatusChoices.RUNNING,
                process_type=Process.TypeChoices.ORCHESTRATOR,
            )
            for proc in running:
                try:
                    proc.kill_tree(graceful_timeout=0.5)
                except Exception:
                    continue

            supervisor = get_supervisor()

            try:
                stop_worker(supervisor, RUNNER_WORKER["name"])
            except Exception:
                pass

            start_worker(supervisor, RUNNER_WORKER)

        def runner_running() -> bool:
            proc = get_worker(get_supervisor(), RUNNER_WORKER["name"])
            return bool(proc and proc.get("statename") == "RUNNING")

        while True:
            try:
                if os.path.exists(pidfile):
                    with open(pidfile) as handle:
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
