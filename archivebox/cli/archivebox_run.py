#!/usr/bin/env python3

"""
archivebox run [--daemon] [--crawl-id=...] [--snapshot-id=...] [--binary-id=...]

Unified command for processing queued work on the shared abx-dl bus.

Modes:
    - With stdin JSONL: Process piped records, exit when complete
    - Without stdin (TTY): Run the background runner in foreground until killed
    - --crawl-id: Run the crawl runner for a specific crawl only
    - --snapshot-id: Run a specific snapshot through its parent crawl
    - --binary-id: Emit a BinaryRequestEvent for a specific Binary row

Examples:
    # Run the background runner in foreground
    archivebox run

    # Run as daemon (don't exit on idle)
    archivebox run --daemon

    # Process specific records (pipe any JSONL type, exits when done)
    archivebox snapshot list --status=queued | archivebox run
    archivebox archiveresult list --status=failed | archivebox run
    archivebox crawl list --status=queued | archivebox run

    # Mixed types work too
    cat mixed_records.jsonl | archivebox run

    # Run the crawl runner for a specific crawl
    archivebox run --crawl-id=019b7e90-04d0-73ed-adec-aad9cfcd863e

    # Run one snapshot from an existing crawl
    archivebox run --snapshot-id=019b7e90-5a8e-712c-9877-2c70eebe80ad

    # Run one queued binary install directly on the bus
    archivebox run --binary-id=019b7e90-5a8e-712c-9877-2c70eebe80ad
"""

__package__ = "archivebox.cli"
__command__ = "archivebox run"

import asyncio
import os
import signal
import sys
from collections import defaultdict

import rich_click as click
from rich import print as rprint


RUNNER_DAEMON_ENV = "ARCHIVEBOX_RUNNER_DAEMON"


def _exit_daemon_runner_on_signal(sig: signal.Signals) -> None:
    os._exit(128 + int(sig))


def process_stdin_records() -> int:
    """
    Process JSONL records from stdin.

    Create-or-update behavior:
    - Records WITHOUT id: Create via Model.from_json(), then queue
    - Records WITH id: Lookup existing, re-queue for processing

    Outputs JSONL of all processed records (for chaining).

    Handles any record type: Crawl, Snapshot, ArchiveResult.
    Auto-cascades: Crawl → Snapshots → ArchiveResults.

    Returns exit code (0 = success, 1 = error).
    """
    from django.utils import timezone

    from archivebox.misc.jsonl import (
        read_stdin,
        write_record,
        TYPE_CRAWL,
        TYPE_SNAPSHOT,
        TYPE_ARCHIVERESULT,
        TYPE_BINARYREQUEST,
        TYPE_BINARY,
    )
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Snapshot, ArchiveResult
    from archivebox.crawls.models import Crawl
    from archivebox.core.shutdown_util import foreground_parent_watchdog, foreground_shutdown_signals
    from archivebox.machine.models import Binary
    from archivebox.services.runner import run_binary, run_crawl

    records = list(read_stdin())
    is_tty = sys.stdout.isatty()

    if not records:
        return 0  # Nothing to process

    created_by_id = get_or_create_system_user_pk()
    queued_count = 0
    output_records = []
    full_crawl_ids: set[str] = set()
    snapshot_ids_by_crawl: dict[str, set[str]] = defaultdict(set)
    plugin_names_by_crawl: dict[str, set[str]] = defaultdict(set)
    run_all_plugins_for_crawl: set[str] = set()
    binary_ids: list[str] = []

    for record in records:
        record_type = record.get("type", "")
        record_id = record.get("id")

        try:
            if record_type == TYPE_CRAWL:
                if record_id:
                    # Existing crawl - re-queue
                    try:
                        crawl = Crawl.objects.get(id=record_id)
                    except Crawl.DoesNotExist:
                        crawl = Crawl.from_json(record, overrides={"created_by_id": created_by_id})
                else:
                    # New crawl - create it
                    crawl = Crawl.from_json(record, overrides={"created_by_id": created_by_id})

                if crawl:
                    crawl.update_and_requeue(
                        status=Crawl.StatusChoices.QUEUED,
                        retry_at=timezone.now(),
                    )
                    full_crawl_ids.add(str(crawl.id))
                    run_all_plugins_for_crawl.add(str(crawl.id))
                    output_records.append(crawl.to_json())
                    queued_count += 1

            elif record_type == TYPE_SNAPSHOT or (record.get("url") and not record_type):
                if record_id:
                    # Existing snapshot - re-queue
                    try:
                        snapshot = Snapshot.objects.get(id=record_id)
                    except Snapshot.DoesNotExist:
                        snapshot = Snapshot.from_json(record, overrides={"created_by_id": created_by_id})
                else:
                    # New snapshot - create it
                    snapshot = Snapshot.from_json(record, overrides={"created_by_id": created_by_id})

                if snapshot:
                    snapshot.queue_for_extraction()
                    crawl_id = str(snapshot.crawl_id)
                    snapshot_ids_by_crawl[crawl_id].add(str(snapshot.id))
                    run_all_plugins_for_crawl.add(crawl_id)
                    output_records.append(snapshot.to_json())
                    queued_count += 1

            elif record_type == TYPE_ARCHIVERESULT:
                if record_id:
                    # Existing archiveresult - re-queue
                    try:
                        archiveresult = ArchiveResult.objects.get(id=record_id)
                    except ArchiveResult.DoesNotExist:
                        archiveresult = None
                else:
                    archiveresult = None

                snapshot_id = record.get("snapshot_id")
                plugin_name = record.get("plugin")
                snapshot = None
                if archiveresult:
                    if archiveresult.status in [
                        ArchiveResult.StatusChoices.FAILED,
                        ArchiveResult.StatusChoices.SKIPPED,
                        ArchiveResult.StatusChoices.NORESULTS,
                        ArchiveResult.StatusChoices.BACKOFF,
                    ]:
                        archiveresult.reset_for_retry()
                    snapshot = archiveresult.snapshot
                    plugin_name = plugin_name or archiveresult.plugin
                elif snapshot_id:
                    try:
                        snapshot = Snapshot.objects.get(id=snapshot_id)
                    except Snapshot.DoesNotExist:
                        snapshot = None

                if snapshot:
                    snapshot.queue_for_extraction()
                    crawl_id = str(snapshot.crawl_id)
                    snapshot_ids_by_crawl[crawl_id].add(str(snapshot.id))
                    if plugin_name:
                        plugin_names_by_crawl[crawl_id].add(str(plugin_name))
                    output_records.append(record if not archiveresult else archiveresult.to_json())
                    queued_count += 1

            elif record_type in {TYPE_BINARYREQUEST, TYPE_BINARY}:
                if record_id:
                    try:
                        binary = Binary.objects.get(id=record_id)
                    except Binary.DoesNotExist:
                        binary = Binary.from_json(record)
                else:
                    binary = Binary.from_json(record)

                if binary:
                    binary.retry_at = timezone.now()
                    if binary.status != Binary.StatusChoices.INSTALLED:
                        binary.status = Binary.StatusChoices.QUEUED
                    binary.save()
                    binary_ids.append(str(binary.id))
                    output_records.append(binary.to_json())
                    queued_count += 1

            else:
                # Unknown type - pass through
                output_records.append(record)

        except Exception as e:
            rprint(f"[yellow]Error processing record: {e}[/yellow]", file=sys.stderr)
            continue

    # Output all processed records (for chaining)
    if not is_tty:
        for rec in output_records:
            write_record(rec)

    if queued_count == 0:
        rprint("[yellow]No records to process[/yellow]", file=sys.stderr)
        return 0

    rprint(f"[blue]Processing {queued_count} records...[/blue]", file=sys.stderr)

    for binary_id in binary_ids:
        run_binary(binary_id)

    targeted_crawl_ids = full_crawl_ids | set(snapshot_ids_by_crawl)
    if targeted_crawl_ids:
        for crawl_id in sorted(targeted_crawl_ids):
            try:
                crawl = Crawl.objects.get(id=crawl_id)
            except Crawl.DoesNotExist:
                continue
            if not crawl.claim_processing_lock(lock_seconds=10):
                rprint(f"[yellow]Crawl {crawl_id} is already owned by another runner[/yellow]", file=sys.stderr)
                return 1
            with foreground_shutdown_signals(), foreground_parent_watchdog():
                run_crawl(
                    crawl_id,
                    snapshot_ids=None if crawl_id in full_crawl_ids else sorted(snapshot_ids_by_crawl[crawl_id]),
                    selected_plugins=None if crawl_id in run_all_plugins_for_crawl else sorted(plugin_names_by_crawl[crawl_id]),
                    selected_plugins_are_explicit=False,
                )
    return 0


def run_runner(daemon: bool = False, crawl_id: str | None = None, maintenance_only: bool = False) -> int:
    """
    Run the background runner loop.

    Args:
        daemon: Run forever (don't exit when idle)

    Returns exit code (0 = success, 1 = error).
    """
    from archivebox.config import CONSTANTS
    from archivebox.core.shutdown_util import foreground_parent_watchdog, foreground_shutdown_signals
    from archivebox.machine.models import Machine, Process
    from archivebox.core.takeover_util import enter_single_runner_gate, standby_until_foreground_runner_needed
    from archivebox.core.recovery_util import recover_orchestrator_state
    from archivebox.services.runner import run_pending_crawls

    Machine.current()
    current = Process.current()
    root_command = current.root
    if daemon and root_command.process_type in (
        Process.TypeChoices.SERVER,
        Process.TypeChoices.ADD,
        Process.TypeChoices.UPDATE,
    ):
        # Server-owned daemon runners are persistent supervisor workers, but
        # foreground add/update commands are allowed to borrow runner/sonic
        # leadership without taking down Daphne. Waiting here keeps the worker
        # on the normal runner path while preventing a server restart loop from
        # immediately stealing the single-runner gate back from the newer CLI.
        standby_until_foreground_runner_needed(root_command, data_dir=CONSTANTS.DATA_DIR)
    if not enter_single_runner_gate(current, data_dir=CONSTANTS.DATA_DIR):
        current.mark_exited()
        return 0

    recover_orchestrator_state(include_chrome=True)
    if crawl_id:
        from django.utils import timezone
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.filter(id=crawl_id, status__in=Crawl.RUNNABLE_STATES).first()
        now = timezone.now()
        # Only re-lease when the row is unscheduled (retry_at IS NULL) or its
        # existing lease has already expired. A future retry_at means another
        # worker is already scheduled — don't clobber.
        if crawl is not None and (crawl.retry_at is None or crawl.retry_at <= now):
            # extra_filter pins the read-time retry_at so a concurrent worker
            # that grabbed the lease between our SELECT and UPDATE wins.
            crawl.safe_update(
                {"retry_at": now},
                refresh=False,
                extra_filter={"retry_at": crawl.retry_at},
            )
    # Only a foreground `archivebox add` gets the interactive "abort current
    # hook, continue/retry, second Ctrl+C exits" flow. Server/update/run owned
    # orchestrators should shut down immediately and cleanly on the first signal.
    interactive_interrupts = current.root.process_type == Process.TypeChoices.ADD
    if daemon:
        os.environ[RUNNER_DAEMON_ENV] = "1"
    try:
        with (
            foreground_shutdown_signals(
                on_signal=_exit_daemon_runner_on_signal if daemon else None,
                raise_on_first_signal=not daemon,
            ),
            foreground_parent_watchdog(enabled=not daemon),
        ):
            run_pending_crawls(
                daemon=daemon,
                crawl_id=crawl_id,
                maintenance_only=maintenance_only,
                interactive_interrupts=interactive_interrupts,
            )
        return 0
    except KeyboardInterrupt:
        return 0
    except asyncio.CancelledError as e:
        if daemon:
            rprint(f"[red]Runner cancelled unexpectedly: {type(e).__name__}: {e}[/red]", file=sys.stderr)
            return 1
        return 0
    except Exception as e:
        rprint(f"[red]Runner error: {type(e).__name__}: {e}[/red]", file=sys.stderr)
        return 1
    finally:
        current.refresh_from_db()
        if current.status != Process.StatusChoices.EXITED:
            current.mark_exited()


@click.command()
@click.option("--daemon", "-d", is_flag=True, help="Run forever (don't exit on idle)")
@click.option("--crawl-id", help="Run the crawl runner for a specific crawl only")
@click.option("--snapshot-id", help="Run one snapshot through its crawl")
@click.option("--binary-id", help="Run one queued binary install directly on the bus")
@click.option("--maintenance-only", is_flag=True, help="Only process due maintenance ticks on sealed/paused snapshots")
@click.option("--no-stdin", is_flag=True, hidden=True, help="Run the scheduler even when stdin is not a TTY")
def main(daemon: bool, crawl_id: str, snapshot_id: str, binary_id: str, maintenance_only: bool, no_stdin: bool):
    """
    Process queued work.

    Modes:
    - No args + stdin piped: Process piped JSONL records
    - No args + TTY: Run the crawl runner for all work
    - --crawl-id: Run the crawl runner for that crawl only
    - --snapshot-id: Run one snapshot through its crawl only
    - --binary-id: Run one queued binary install directly on the bus
    """
    from archivebox.core.shutdown_util import foreground_parent_watchdog, foreground_shutdown_signals

    if daemon and not snapshot_id and not binary_id and not crawl_id:
        try:
            os.environ[RUNNER_DAEMON_ENV] = "1"
            with (
                foreground_shutdown_signals(
                    on_signal=_exit_daemon_runner_on_signal,
                    raise_on_first_signal=False,
                ),
                foreground_parent_watchdog(enabled=False),
            ):
                sys.exit(run_runner(daemon=True, maintenance_only=maintenance_only))
        except KeyboardInterrupt:
            sys.exit(0)

    with foreground_shutdown_signals(), foreground_parent_watchdog(enabled=not daemon):
        if snapshot_id:
            sys.exit(run_snapshot_worker(snapshot_id))

        if binary_id:
            try:
                from archivebox.services.runner import run_binary

                run_binary(binary_id)
                sys.exit(0)
            except KeyboardInterrupt:
                sys.exit(0)
            except Exception as e:
                rprint(f"[red]Runner error: {type(e).__name__}: {e}[/red]", file=sys.stderr)
                import traceback

                traceback.print_exc()
                sys.exit(1)

        if crawl_id:
            sys.exit(run_runner(daemon=False, crawl_id=crawl_id, maintenance_only=maintenance_only))

        if maintenance_only:
            sys.exit(run_runner(daemon=daemon, maintenance_only=True))

        if not no_stdin and not sys.stdin.isatty():
            sys.exit(process_stdin_records())
        else:
            sys.exit(run_runner(daemon=daemon, maintenance_only=maintenance_only))


def run_snapshot_worker(snapshot_id: str) -> int:
    from archivebox.core.shutdown_util import foreground_parent_watchdog, foreground_shutdown_signals
    from archivebox.core.models import Snapshot
    from archivebox.services.runner import run_due_snapshot
    from django.utils import timezone

    snapshot = None
    try:
        with foreground_shutdown_signals(), foreground_parent_watchdog():
            for _ in range(10):
                snapshot = Snapshot.objects.select_related("crawl").get(id=snapshot_id)
                if snapshot.retry_at is None:
                    snapshot.update_and_requeue(retry_at=timezone.now())
                elif snapshot.retry_at > timezone.now():
                    break
                if not run_due_snapshot(snapshot, lock_seconds=60):
                    break
        return 0
    except KeyboardInterrupt:
        try:
            if snapshot is not None:
                snapshot.refresh_from_db()
            else:
                snapshot = Snapshot.objects.filter(id=snapshot_id).first()
            if snapshot is not None and snapshot.status != Snapshot.StatusChoices.SEALED:
                snapshot.update_and_requeue(retry_at=timezone.now())
        except Exception:
            pass
        return 0
    except Exception as e:
        rprint(f"[red]Runner error: {type(e).__name__}: {e}[/red]", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    main()
