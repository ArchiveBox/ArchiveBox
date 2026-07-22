from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Watch the debug runserver Process row and restart the background runner on autoreloads."

    def add_arguments(self, parser):
        parser.add_argument(
            "--bind-url",
            default="",
            help="Runserver bind URL to watch, e.g. http://127.0.0.1:8000",
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

        from archivebox.config import CONSTANTS
        from archivebox.machine.models import Machine, Process
        from archivebox.workers.supervisord_util import (
            RUNNER_WORKER,
            SupervisordConnectionCache,
            get_worker,
            start_worker,
            stop_worker,
        )

        bind_url = kwargs.get("bind_url") or os.environ.get("ARCHIVEBOX_RUNSERVER_BIND_URL") or ""
        current = Process.current()
        current.mark_running(
            process_type=Process.TypeChoices.WORKER,
            worker_type="worker_runner_watch",
            pwd=str(CONSTANTS.DATA_DIR),
            url=bind_url,
            timeout=CONSTANTS.MAX_HOOK_RUNTIME_SECONDS,
        )

        interval = max(0.2, float(kwargs.get("interval", 1.0)))
        last_runserver_id = None
        supervisor_cache = SupervisordConnectionCache()

        def stop_duplicate_watchers() -> None:
            machine = Machine.current()
            for proc in Process.objects.filter(
                machine=machine,
                status=Process.StatusChoices.RUNNING,
                process_type=Process.TypeChoices.WORKER,
                worker_type="worker_runner_watch",
                pwd=str(CONSTANTS.DATA_DIR),
                url=bind_url,
            ).exclude(id=current.id):
                if proc.is_running:
                    proc.terminate(graceful_timeout=2.0)

        def get_supervisor():
            supervisor = supervisor_cache.get()
            if supervisor is None:
                raise RuntimeError("runner_watch requires a running supervisord process")
            return supervisor

        def current_runserver():
            machine = Machine.current()
            for proc in Process.objects.filter(
                machine=machine,
                status=Process.StatusChoices.RUNNING,
                process_type=Process.TypeChoices.WORKER,
                worker_type="worker_runserver",
                pwd=str(CONSTANTS.DATA_DIR),
                url=bind_url,
            ).order_by("-started_at", "-created_at"):
                if proc.is_running:
                    return proc
            return None

        stop_duplicate_watchers()
        start_worker(get_supervisor(), RUNNER_WORKER, lazy=True)

        def restart_runner() -> None:
            machine = Machine.current()

            for proc in Process.objects.filter(
                machine=machine,
                status=Process.StatusChoices.RUNNING,
                process_type=Process.TypeChoices.ORCHESTRATOR,
                pwd=str(CONSTANTS.DATA_DIR),
            ):
                if proc.is_running:
                    proc.kill_tree(graceful_timeout=0.5)

            supervisor = get_supervisor()
            try:
                stop_worker(supervisor, RUNNER_WORKER()["name"])
            except Exception:
                pass
            start_worker(supervisor, RUNNER_WORKER())

        def runner_running() -> bool:
            proc = get_worker(get_supervisor(), RUNNER_WORKER()["name"])
            return bool(proc and proc.get("statename") == "RUNNING")

        while True:
            try:
                runserver = current_runserver()
                runserver_id = str(runserver.id) if runserver else None
                if runserver_id and runserver_id != last_runserver_id:
                    restart_runner()
                    last_runserver_id = runserver_id
                elif not runner_running():
                    restart_runner()
                current.heartbeat()
            except Exception:
                supervisor_cache.clear()
                pass

            time.sleep(interval)
