from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Watch the runserver autoreload PID file and restart orchestrator on reloads."

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
        from archivebox.config.common import STORAGE_CONFIG
        from archivebox.machine.models import Process, Machine
        from archivebox.workers.orchestrator import Orchestrator

        os.environ['ARCHIVEBOX_ORCHESTRATOR_WATCHER'] = '1'

        pidfile = kwargs.get("pidfile") or os.environ.get("ARCHIVEBOX_RUNSERVER_PIDFILE")
        if not pidfile:
            pidfile = str(STORAGE_CONFIG.TMP_DIR / "runserver.pid")

        interval = max(0.2, float(kwargs.get("interval", 1.0)))

        last_pid = None

        def restart_orchestrator():
            Process.cleanup_stale_running()
            machine = Machine.current()

            running = Process.objects.filter(
                machine=machine,
                status=Process.StatusChoices.RUNNING,
                process_type__in=[
                    Process.TypeChoices.ORCHESTRATOR,
                    Process.TypeChoices.WORKER,
                    Process.TypeChoices.HOOK,
                ],
            )
            for proc in running:
                try:
                    if proc.process_type == Process.TypeChoices.HOOK:
                        proc.kill_tree(graceful_timeout=0.5)
                    else:
                        proc.terminate(graceful_timeout=1.0)
                except Exception:
                    continue

            if not Orchestrator.is_running():
                Orchestrator(exit_on_idle=False).start()

        while True:
            try:
                if os.path.exists(pidfile):
                    with open(pidfile, "r") as handle:
                        pid = handle.read().strip() or None
                else:
                    pid = None

                if pid and pid != last_pid:
                    restart_orchestrator()
                    last_pid = pid
                elif not Orchestrator.is_running():
                    Orchestrator(exit_on_idle=False).start()

            except Exception:
                pass

            time.sleep(interval)
