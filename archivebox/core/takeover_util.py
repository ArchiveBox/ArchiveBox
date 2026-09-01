from __future__ import annotations

import time
import sys
from collections.abc import Callable
from pathlib import Path

from django.db import IntegrityError
from django.utils import timezone
from archivebox.config import CONSTANTS
from archivebox.config.common import rprint

RUNNER_ACTIVE_WORKER_TYPE = "worker_runner"
RUNNER_WAITING_WORKER_TYPE = "runner_waiting"
RUNNER_GATE_WORKER_TYPES = (RUNNER_ACTIVE_WORKER_TYPE, RUNNER_WAITING_WORKER_TYPE, "")


def runtime_stack_owner_types():
    from archivebox.machine.models import Process

    return (
        Process.TypeChoices.SERVER,
        Process.TypeChoices.ORCHESTRATOR,
    )


def foreground_runner_owner_types():
    from archivebox.machine.models import Process

    return (
        Process.TypeChoices.SERVER,
        Process.TypeChoices.ADD,
        Process.TypeChoices.UPDATE,
    )


def current_command(process_type: str, *, data_dir: str | Path, url: str | None = None):
    from archivebox.machine.models import Process

    proc = Process.current()
    proc.mark_running(process_type=process_type, pwd=str(data_dir), url=url, timeout=CONSTANTS.MAX_HOOK_RUNTIME_SECONDS)
    return proc


def live_processes(*, process_type: str, data_dir: str | Path, url: str | None = None):
    from archivebox.machine.models import Machine, Process

    qs = Process.objects.filter(
        machine=Machine.current(),
        process_type=process_type,
        status=Process.StatusChoices.RUNNING,
        pwd=str(data_dir),
    )
    if url is not None:
        qs = qs.filter(url=url)
    return [proc for proc in qs.order_by("-created_at", "-modified_at").iterator(chunk_size=50) if proc.is_running]


def newest_live_process(*, process_type: str, data_dir: str | Path, url: str | None = None):
    processes = live_processes(process_type=process_type, data_dir=data_dir, url=url)
    return processes[0] if processes else None


def command_is_newest(command, *, process_type: str, data_dir: str | Path, url: str | None = None) -> bool:
    leader = newest_live_process(process_type=process_type, data_dir=data_dir, url=url)
    return bool(leader and leader.id == command.id)


def runtime_stack_owner(*, data_dir: str | Path, exclude_id=None):
    from archivebox.machine.models import Machine, Process

    machine = Machine.current()
    base_qs = Process.objects.filter(
        machine=machine,
        status=Process.StatusChoices.RUNNING,
        pwd=str(data_dir),
        process_type__in=runtime_stack_owner_types(),
    )
    if exclude_id is not None:
        base_qs = base_qs.exclude(id=exclude_id)

    for qs in (
        # Only server parents own HTTP runtime leadership. Foreground add/update
        # commands can own runner/sonic components, but server startup must never
        # wait behind them before binding Daphne.
        base_qs.filter(process_type=Process.TypeChoices.SERVER),
        # A foreground `archivebox run` process is allowed to own the runtime
        # stack when no server/add parent is alive. A runner launched by
        # supervisord is only a child worker; after its parent is killed it must
        # not keep stealing leadership from the next foreground command.
        base_qs.filter(process_type=Process.TypeChoices.ORCHESTRATOR).exclude(parent__process_type=Process.TypeChoices.SUPERVISORD),
    ):
        for proc in qs.order_by("-created_at", "-modified_at").iterator(chunk_size=50):
            if proc.is_running:
                return proc
            proc.mark_exited(exit_code=proc.exit_code if proc.exit_code is not None else 0)
    return None


def command_owns_runtime_stack(command, *, data_dir: str | Path) -> bool:
    owner = runtime_stack_owner(data_dir=data_dir)
    return bool(owner and owner.id == command.id)


def foreground_runner_owner(*, data_dir: str | Path, exclude_id=None):
    from archivebox.machine.models import Machine, Process

    machine = Machine.current()
    qs = Process.objects.filter(
        machine=machine,
        status=Process.StatusChoices.RUNNING,
        pwd=str(data_dir),
        process_type__in=foreground_runner_owner_types(),
    )
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    for proc in qs.order_by("-created_at", "-modified_at").iterator(chunk_size=50):
        if proc.is_running:
            return proc
        proc.mark_exited(exit_code=proc.exit_code if proc.exit_code is not None else 0)
    return None


def command_owns_foreground_runner(command, *, data_dir: str | Path) -> bool:
    owner = foreground_runner_owner(data_dir=data_dir)
    return bool(owner and owner.id == command.id)


def runtime_stack_component_label(*, owner=None, data_dir: str | Path) -> str:
    try:
        from archivebox.workers.supervisord_util import active_supervisord_runtime_components

        components = active_supervisord_runtime_components()
    except Exception:
        components = []

    names = list(components)
    if not names and owner is not None:
        from archivebox.machine.models import Process

        if owner.process_type == Process.TypeChoices.SERVER:
            names = ["orchestrator", "server"]
        elif owner.process_type == Process.TypeChoices.ORCHESTRATOR:
            names = ["orchestrator"]

    return ", ".join(dict.fromkeys(names)) or "runtime stack"


def ensure_daemon_stack(*, reason: str = ""):
    from archivebox.config.common import get_config
    from archivebox.workers.supervisord_util import (
        get_existing_supervisord_process,
        get_or_create_supervisord_process,
        get_sonic_supervisord_worker_from_plugin,
        get_worker,
        start_worker,
    )

    config = get_config()
    sonic_worker = get_sonic_supervisord_worker_from_plugin(config)
    if sonic_worker is None:
        return None

    from abx_plugins.plugins.search_backend_sonic.daemon import is_port_listening, prepare_sonic_daemon

    sonic_event = prepare_sonic_daemon(config)
    if is_port_listening(sonic_event.host, sonic_event.port):
        return {
            "name": sonic_event.worker_name,
            "statename": "RUNNING",
            "description": f"existing Sonic daemon at {sonic_event.url}",
        }

    supervisor = get_existing_supervisord_process() or get_or_create_supervisord_process(daemonize=False)
    worker = get_worker(supervisor, sonic_worker["name"])
    if isinstance(worker, dict) and worker.get("statename") in ("STARTING", "RUNNING"):
        return worker

    if reason:
        rprint(f"[yellow][*] Starting daemon stack for {reason}...[/yellow]")
    return start_worker(supervisor, sonic_worker)


def healthy_orchestrator(*, data_dir: str | Path):
    from archivebox.machine.models import Machine, Process
    from archivebox.workers.supervisord_util import get_existing_supervisord_process, get_worker

    supervisor = get_existing_supervisord_process()
    worker = get_worker(supervisor, "worker_runner") if supervisor else None
    if isinstance(worker, dict) and worker.get("statename") in ("STARTING", "RUNNING"):
        return worker

    for proc in Process.objects.filter(
        machine=Machine.current(),
        process_type=Process.TypeChoices.ORCHESTRATOR,
        status=Process.StatusChoices.RUNNING,
        pwd=str(data_dir),
    ).order_by("-created_at"):
        if proc.is_running:
            return proc
    return None


def _runner_sort_key(process):
    return (process.started_at or process.created_at, process.created_at, str(process.id))


def live_runner_processes(*, data_dir: str | Path, exclude_id=None):
    from archivebox.machine.models import Machine, Process

    machine = Machine.current()
    Process.cleanup_stale_running(machine=machine)
    qs = Process.objects.filter(
        status=Process.StatusChoices.RUNNING,
        process_type=Process.TypeChoices.ORCHESTRATOR,
        worker_type__in=RUNNER_GATE_WORKER_TYPES,
        pwd=str(data_dir),
    )
    foreign_machine_exists = qs.exclude(machine=machine).exists()
    qs = qs.filter(machine=machine)
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)

    live = []
    foreign_namespace_ids = []
    for process in qs.order_by("started_at", "created_at").iterator(chunk_size=20):
        if not process.shares_pid_namespace:
            foreign_namespace_ids.append(process.id)
            continue
        if process.is_running:
            live.append(process)
    if foreign_machine_exists or foreign_namespace_ids:
        rprint(
            "[bold yellow]WARNING: Multiple orchestrators sharing a single collection is not officially supported! "
            "Corruption may occur if you run two ArchiveBox workers on the same collection at once.[/bold yellow]",
            file=sys.stderr,
            soft_wrap=True,
        )
    if foreign_namespace_ids:
        now = timezone.now()
        Process.objects.filter(id__in=foreign_namespace_ids, status=Process.StatusChoices.RUNNING).update(
            status=Process.StatusChoices.EXITED,
            exit_code=0,
            ended_at=now,
            retry_at=None,
            modified_at=now,
        )
    return live


def enter_single_runner_gate(command, *, data_dir: str | Path, graceful_timeout: float = 5.0) -> bool:
    """
    Admit exactly one active runner for this DATA_DIR using Process rows.

    The current process is a real OS process while it waits, so we keep its
    Process row RUNNING but mark worker_type=runner_waiting. Only the process
    that wins takeover is promoted to worker_type=worker_runner, which is
    protected by a partial unique DB constraint. Older runners are terminated
    and fully waited out before promotion, so the runner work loop never overlaps.
    """
    from archivebox.machine.models import Process

    command.mark_running(
        process_type=Process.TypeChoices.ORCHESTRATOR,
        worker_type=RUNNER_WAITING_WORKER_TYPE,
        pwd=str(data_dir),
        timeout=CONSTANTS.MAX_HOOK_RUNTIME_SECONDS,
    )
    while True:
        runners = live_runner_processes(data_dir=data_dir)
        if all(process.id != command.id for process in runners):
            command.refresh_from_db()
            command.mark_running(
                process_type=Process.TypeChoices.ORCHESTRATOR,
                worker_type=RUNNER_WAITING_WORKER_TYPE,
                pwd=str(data_dir),
                timeout=CONSTANTS.MAX_HOOK_RUNTIME_SECONDS,
            )
            runners = live_runner_processes(data_dir=data_dir)

        newest = max(runners, key=_runner_sort_key)
        if newest.id != command.id:
            rprint(
                f"[yellow][*] Newer ArchiveBox runner pid={newest.pid} is taking over; exiting this runner.[/yellow]",
                file=sys.stderr,
            )
            return False

        older_runners = [process for process in runners if process.id != command.id]
        if older_runners:
            for process in older_runners:
                rprint(f"[yellow][*] Stopping older ArchiveBox runner process (pid={process.pid})...[/yellow]", file=sys.stderr)
                process.kill_tree(graceful_timeout=graceful_timeout)
            time.sleep(0.1)
            continue

        try:
            command.mark_running(
                process_type=Process.TypeChoices.ORCHESTRATOR,
                worker_type=RUNNER_ACTIVE_WORKER_TYPE,
                pwd=str(data_dir),
                timeout=CONSTANTS.MAX_HOOK_RUNTIME_SECONDS,
            )
            return True
        except IntegrityError:
            # A hard-killed runner may leave the unique active-runner row behind.
            # The next loop starts by proving each RUNNING Process row still maps
            # to a live OS process, then marks dead rows EXITED before retrying.
            command.refresh_from_db()
            time.sleep(0.1)


def standby_until_leader_needed(command, *, process_type: str, data_dir: str | Path, url: str | None = None, interval: float = 2.0) -> None:
    from archivebox.workers.supervisord_util import reap_foreground_supervisord_process

    announced = False
    while not command_is_newest(command, process_type=process_type, data_dir=data_dir, url=url):
        reap_foreground_supervisord_process()
        if not announced:
            leader = newest_live_process(process_type=process_type, data_dir=data_dir, url=url)
            leader_pid = leader.pid if leader else "unknown"
            rprint(f"[yellow][*] Standing by; newer ArchiveBox process pid={leader_pid} is running the orchestrator and server.[/yellow]")
            announced = True
        time.sleep(interval)
    command.modified_at = timezone.now()
    command.save(update_fields=["modified_at"])


def standby_until_runtime_stack_needed(command, *, data_dir: str | Path, interval: float = 2.0) -> dict[str, object]:
    from archivebox.workers.supervisord_util import reap_foreground_supervisord_process

    announced = False
    previous_owner_pid = None
    while not command_owns_runtime_stack(command, data_dir=data_dir):
        reap_foreground_supervisord_process()
        if not announced:
            owner = runtime_stack_owner(data_dir=data_dir)
            owner_pid = owner.pid if owner else "unknown"
            components = runtime_stack_component_label(owner=owner, data_dir=data_dir)
            previous_owner_pid = owner_pid
            rprint(
                f"[yellow][*] A newer archivebox process took over the {components} "
                f"(pid={owner_pid}). Work will continue there, and will resume here if that process exits and work still remains.[/yellow]",
                file=sys.stderr,
            )
            announced = True
        time.sleep(interval)
    command.modified_at = timezone.now()
    command.save(update_fields=["modified_at"])
    return {"resumed": announced, "previous_owner_pid": previous_owner_pid}


def standby_until_foreground_runner_needed(
    command,
    *,
    data_dir: str | Path,
    interval: float = 2.0,
    work_is_complete: Callable[[], bool] | None = None,
) -> dict[str, object]:
    from archivebox.workers.supervisord_util import reap_foreground_supervisord_process

    announced = False
    previous_owner_pid = None
    while True:
        if work_is_complete is not None and work_is_complete():
            return {"resumed": announced, "previous_owner_pid": previous_owner_pid, "work_completed": True}
        if command_owns_foreground_runner(command, data_dir=data_dir):
            break
        reap_foreground_supervisord_process()
        if not announced:
            owner = foreground_runner_owner(data_dir=data_dir)
            owner_pid = owner.pid if owner else "unknown"
            previous_owner_pid = owner_pid
            rprint(
                f"[yellow][*] A newer archivebox process took over the orchestrator, sonic "
                f"(pid={owner_pid}). Work will continue there, and will resume here if that process exits and work still remains.[/yellow]",
                file=sys.stderr,
            )
            announced = True
        time.sleep(interval)
    command.modified_at = timezone.now()
    command.save(update_fields=["modified_at"])
    return {"resumed": announced, "previous_owner_pid": previous_owner_pid, "work_completed": False}
