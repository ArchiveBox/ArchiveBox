#!/usr/bin/env python3

"""
archivebox run [--daemon]

Unified command for processing queued work.

Modes:
    - With stdin JSONL: Process piped records, exit when complete
    - Without stdin (TTY): Run orchestrator in foreground until killed

Examples:
    # Run orchestrator in foreground (replaces `archivebox orchestrator`)
    archivebox run

    # Run as daemon (don't exit on idle)
    archivebox run --daemon

    # Process specific records (pipe any JSONL type, exits when done)
    archivebox snapshot list --status=queued | archivebox run
    archivebox archiveresult list --status=failed | archivebox run
    archivebox crawl list --status=queued | archivebox run

    # Mixed types work too
    cat mixed_records.jsonl | archivebox run
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox run'

import sys

import rich_click as click
from rich import print as rprint


def process_stdin_records() -> int:
    """
    Process JSONL records from stdin.

    Create-or-update behavior:
    - Records WITHOUT id: Create via Model.from_json(), then queue
    - Records WITH id: Lookup existing, re-queue for processing

    Outputs JSONL of all processed records (for chaining).

    Handles any record type: Crawl, Snapshot, ArchiveResult.
    Auto-cascades: Crawl → Snapshots → ArchiveResults.

    Uses inline mode for fast processing (no subprocess overhead).

    Returns exit code (0 = success, 1 = error).
    """
    from django.utils import timezone

    from archivebox.misc.jsonl import read_stdin, write_record, TYPE_CRAWL, TYPE_SNAPSHOT, TYPE_ARCHIVERESULT
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Snapshot, ArchiveResult
    from archivebox.crawls.models import Crawl
    from archivebox.workers.orchestrator import Orchestrator

    records = list(read_stdin())
    is_tty = sys.stdout.isatty()

    if not records:
        return 0  # Nothing to process

    created_by_id = get_or_create_system_user_pk()
    queued_count = 0
    output_records = []

    for record in records:
        record_type = record.get('type', '')
        record_id = record.get('id')

        try:
            if record_type == TYPE_CRAWL:
                if record_id:
                    # Existing crawl - re-queue
                    try:
                        crawl = Crawl.objects.get(id=record_id)
                    except Crawl.DoesNotExist:
                        crawl = Crawl.from_json(record, overrides={'created_by_id': created_by_id})
                else:
                    # New crawl - create it
                    crawl = Crawl.from_json(record, overrides={'created_by_id': created_by_id})

                if crawl:
                    crawl.retry_at = timezone.now()
                    if crawl.status not in [Crawl.StatusChoices.SEALED]:
                        crawl.status = Crawl.StatusChoices.QUEUED
                    crawl.save()
                    output_records.append(crawl.to_json())
                    queued_count += 1

            elif record_type == TYPE_SNAPSHOT or (record.get('url') and not record_type):
                if record_id:
                    # Existing snapshot - re-queue
                    try:
                        snapshot = Snapshot.objects.get(id=record_id)
                    except Snapshot.DoesNotExist:
                        snapshot = Snapshot.from_json(record, overrides={'created_by_id': created_by_id})
                else:
                    # New snapshot - create it
                    snapshot = Snapshot.from_json(record, overrides={'created_by_id': created_by_id})

                if snapshot:
                    snapshot.retry_at = timezone.now()
                    if snapshot.status not in [Snapshot.StatusChoices.SEALED]:
                        snapshot.status = Snapshot.StatusChoices.QUEUED
                    snapshot.save()
                    output_records.append(snapshot.to_json())
                    queued_count += 1

            elif record_type == TYPE_ARCHIVERESULT:
                if record_id:
                    # Existing archiveresult - re-queue
                    try:
                        archiveresult = ArchiveResult.objects.get(id=record_id)
                    except ArchiveResult.DoesNotExist:
                        archiveresult = ArchiveResult.from_json(record)
                else:
                    # New archiveresult - create it
                    archiveresult = ArchiveResult.from_json(record)

                if archiveresult:
                    archiveresult.retry_at = timezone.now()
                    if archiveresult.status in [ArchiveResult.StatusChoices.FAILED, ArchiveResult.StatusChoices.SKIPPED, ArchiveResult.StatusChoices.BACKOFF]:
                        archiveresult.status = ArchiveResult.StatusChoices.QUEUED
                    archiveresult.save()
                    output_records.append(archiveresult.to_json())
                    queued_count += 1

            else:
                # Unknown type - pass through
                output_records.append(record)

        except Exception as e:
            rprint(f'[yellow]Error processing record: {e}[/yellow]', file=sys.stderr)
            continue

    # Output all processed records (for chaining)
    if not is_tty:
        for rec in output_records:
            write_record(rec)

    if queued_count == 0:
        rprint('[yellow]No records to process[/yellow]', file=sys.stderr)
        return 0

    rprint(f'[blue]Processing {queued_count} records...[/blue]', file=sys.stderr)

    # Run orchestrator with inline=True for fast processing (no subprocess overhead)
    orchestrator = Orchestrator(exit_on_idle=True, inline=True)
    orchestrator.runloop()

    return 0


def run_orchestrator(daemon: bool = False) -> int:
    """
    Run the orchestrator process.

    The orchestrator:
    1. Polls each model queue (Crawl, Snapshot, ArchiveResult)
    2. Spawns worker processes when there is work to do
    3. Monitors worker health and restarts failed workers
    4. Exits when all queues are empty (unless --daemon)

    Args:
        daemon: Run forever (don't exit when idle)

    Returns exit code (0 = success, 1 = error).
    """
    from archivebox.workers.orchestrator import Orchestrator

    if Orchestrator.is_running():
        rprint('[yellow]Orchestrator is already running[/yellow]', file=sys.stderr)
        return 0

    try:
        orchestrator = Orchestrator(exit_on_idle=not daemon)
        orchestrator.runloop()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        rprint(f'[red]Orchestrator error: {type(e).__name__}: {e}[/red]', file=sys.stderr)
        return 1


@click.command()
@click.option('--daemon', '-d', is_flag=True, help="Run forever (don't exit on idle)")
def main(daemon: bool):
    """
    Process queued work.

    When stdin is piped: Process those specific records and exit (uses inline mode).
    When run standalone: Run orchestrator in foreground.
    """
    # Check if stdin has data (non-TTY means piped input)
    if not sys.stdin.isatty():
        sys.exit(process_stdin_records())
    else:
        sys.exit(run_orchestrator(daemon=daemon))


if __name__ == '__main__':
    main()
