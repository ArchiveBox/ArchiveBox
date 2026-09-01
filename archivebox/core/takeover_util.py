"""Coordinate local foreground processes without pretending to provide a distributed lock.

ArchiveBox wants one orchestrator per collection, but Process rows can only prove
liveness for PIDs visible on the current machine/PID namespace. We therefore
enforce one active runner per ``(Machine, DATA_DIR)`` locally, retire stale rows
from sequential containers on that machine, and only warn about rows owned by a
different machine. Foreign-machine rows must never block progress or be killed:
multi-machine coordination belongs in the Crawl/Snapshot CAS claim layer, not in
process takeover.

These helpers only hand local supervisord/runner ownership between CLI parents.
They must not hold database transactions or filesystem locks while work runs.
"""

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


def current_command(process_type: str, *, data_dir: str | Path, url: str | None = None):
    from archivebox.machine.models import Process

    proc = Process.current()
    proc.mark_running(process_type=process_type, pwd=str(data_dir), url=url, timeout=CONSTANTS.MAX_HOOK_RUNTIME_SECONDS)
    return proc


def runtime_stack_owner(*, data_dir: str | Path, exclude_id=None):
    """Return the live local parent allowed to own the server runtime stack."""
    from archivebox.machine.models import Machine, Process

    machine = Machine.current()
    base_qs = Process.objects.filter(
        machine=machine,
        status=Process.StatusChoices.RUNNING,
        pwd=str(data_dir),
        process_type__in=(Process.TypeChoices.SERVER, Process.TypeChoices.ORCHESTRATOR),
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
    """Return the newest live local parent allowed to borrow runner/sonic."""
    from archivebox.machine.models import Machine, Process

    machine = Machine.current()
    qs = Process.objects.filter(
        machine=machine,
        status=Process.StatusChoices.RUNNING,
        pwd=str(data_dir),
        process_type__in=(Process.TypeChoices.SERVER, Process.TypeChoices.ADD, Process.TypeChoices.UPDATE),
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


def live_runner_processes(*, data_dir: str | Path):
    """Return locally verifiable runners and warn about unsupported overlap.

    A Process row from another machine is observability only: its PID cannot be
    checked or signalled here, so it neither joins the local election nor gets
    mutated. A row for this same Machine from another PID namespace represents
    a previous sequential container under the supported model; warn, retire the
    unreachable row, and let the new container continue.
    """
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
    Admit one active runner for this Machine and DATA_DIR using Process rows.

    The current process is a real OS process while it waits, so we keep its
    Process row RUNNING but mark worker_type=runner_waiting. Only the process
    that wins takeover is promoted to worker_type=worker_runner, which is
    protected by a partial unique DB constraint scoped to (Machine, DATA_DIR).
    Older locally verifiable runners are terminated and fully waited out before
    promotion, so runner work never overlaps on one machine. Foreign machines
    are intentionally outside this gate and only produce a warning above.
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

        newest = max(runners, key=lambda process: (process.started_at or process.created_at, process.created_at, str(process.id)))
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


def standby_until_runtime_stack_needed(command, *, data_dir: str | Path, interval: float = 2.0) -> dict[str, object]:
    from archivebox.machine.models import Process
    from archivebox.workers.supervisord_util import active_supervisord_runtime_components, reap_foreground_supervisord_process

    announced = False
    previous_owner_pid = None
    while not command_owns_runtime_stack(command, data_dir=data_dir):
        reap_foreground_supervisord_process()
        if not announced:
            owner = runtime_stack_owner(data_dir=data_dir)
            owner_pid = owner.pid if owner else "unknown"
            try:
                component_names = list(active_supervisord_runtime_components())
            except Exception:
                component_names = []
            if not component_names and owner is not None:
                if owner.process_type == Process.TypeChoices.SERVER:
                    component_names = ["orchestrator", "server"]
                elif owner.process_type == Process.TypeChoices.ORCHESTRATOR:
                    component_names = ["orchestrator"]
            components = ", ".join(dict.fromkeys(component_names)) or "runtime stack"
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
