from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Watch the debug runserver Process row and restart the background runner on autoreloads."

    def add_arguments(self, parser):
        parser.add_argument(
            "--bind-url",
            default="",
            help="Runserver bind URL to watch, e.g. http://127.0.0.1:5797",
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

        from archivebox.config import CONSTANTS
        from archivebox.core.shutdown_util import kill_remaining_processes
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
        supervisor_pid = os.getppid()

        def get_supervisor():
            supervisor = supervisor_cache.get()
            if supervisor is None:
                raise RuntimeError("runner_watch requires a running supervisord process")
            # The socket path is reused during server takeover. This watcher
            # belongs to its original supervisor, never the replacement stack.
            if supervisor.getPID() != supervisor_pid:
                raise SystemExit(0)
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
                if proc.is_running and (local_process := proc.proc) is not None:
                    try:
                        if any(parent.pid == supervisor_pid for parent in local_process.parents()):
                            return proc
                    except psutil.NoSuchProcess:
                        pass
            return None

        # Supervisord already owns exactly one worker with this name. Do not
        # kill other watchers by DATA_DIR: a newer server may be taking over.
        start_worker(get_supervisor(), RUNNER_WORKER(), lazy=True)

        def restart_runner() -> None:
            supervisor = get_supervisor()
            worker = RUNNER_WORKER()
            info = get_worker(supervisor, worker["name"])
            children = []
            if info and info.get("pid"):
                try:
                    root = psutil.Process(info["pid"])
                    if root.ppid() == supervisor_pid:
                        children = root.children(recursive=True)
                except psutil.NoSuchProcess:
                    pass
            # Stop through supervisord FIRST. Killing the PID directly causes
            # autorestart to spawn another runner before stop_worker reaches it.
            # Only this named daemon belongs to the watcher: foreground add/run
            # may currently own the single-runner gate and must stay untouched.
            stop_worker(supervisor, worker["name"])
            # Hooks start separate sessions, so stopasgroup cannot catch every
            # descendant. Keep psutil identities from before reparenting/PID
            # reuse, and finish cleanup before the replacement enters the gate.
            kill_remaining_processes(children)
            start_worker(get_supervisor(), worker)

        def runner_running() -> bool:
            proc = get_worker(get_supervisor(), RUNNER_WORKER()["name"])
            return bool(proc and proc.get("statename") in {"STARTING", "RUNNING", "BACKOFF", "STOPPING"})

        while True:
            try:
                runserver = current_runserver()
                runserver_id = str(runserver.id) if runserver else None
                if runserver_id and last_runserver_id is None:
                    # The first serving process establishes the baseline; it
                    # is not a reload of an already observed web worker.
                    last_runserver_id = runserver_id
                elif runserver_id and runserver_id != last_runserver_id:
                    restart_runner()
                    last_runserver_id = runserver_id
                elif not runner_running():
                    restart_runner()
                current.heartbeat()
            except Exception as err:
                supervisor_cache.clear()
                self.stderr.write(f"runner_watch: {err}")

            time.sleep(interval)
