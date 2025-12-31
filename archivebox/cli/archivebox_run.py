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

    Reads records, queues them for processing, then runs orchestrator until complete.
    Handles any record type: Crawl, Snapshot, ArchiveResult, etc.

    Returns exit code (0 = success, 1 = error).
    """
    from django.utils import timezone

    from archivebox.misc.jsonl import read_stdin, TYPE_CRAWL, TYPE_SNAPSHOT, TYPE_ARCHIVERESULT
    from archivebox.core.models import Snapshot, ArchiveResult
    from archivebox.crawls.models import Crawl
    from archivebox.workers.orchestrator import Orchestrator

    records = list(read_stdin())

    if not records:
        return 0  # Nothing to process

    queued_count = 0

    for record in records:
        record_type = record.get('type')
        record_id = record.get('id')

        if not record_id:
            continue

        try:
            if record_type == TYPE_CRAWL:
                crawl = Crawl.objects.get(id=record_id)
                if crawl.status in [Crawl.StatusChoices.QUEUED, Crawl.StatusChoices.STARTED]:
                    crawl.retry_at = timezone.now()
                    crawl.save()
                    queued_count += 1

            elif record_type == TYPE_SNAPSHOT:
                snapshot = Snapshot.objects.get(id=record_id)
                if snapshot.status in [Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED]:
                    snapshot.retry_at = timezone.now()
                    snapshot.save()
                    queued_count += 1

            elif record_type == TYPE_ARCHIVERESULT:
                archiveresult = ArchiveResult.objects.get(id=record_id)
                if archiveresult.status in [ArchiveResult.StatusChoices.QUEUED, ArchiveResult.StatusChoices.STARTED, ArchiveResult.StatusChoices.BACKOFF]:
                    archiveresult.retry_at = timezone.now()
                    archiveresult.save()
                    queued_count += 1

        except (Crawl.DoesNotExist, Snapshot.DoesNotExist, ArchiveResult.DoesNotExist):
            rprint(f'[yellow]Record not found: {record_type} {record_id}[/yellow]', file=sys.stderr)
            continue

    if queued_count == 0:
        rprint('[yellow]No records to process[/yellow]', file=sys.stderr)
        return 0

    rprint(f'[blue]Processing {queued_count} records...[/blue]', file=sys.stderr)

    # Run orchestrator until all queued work is done
    orchestrator = Orchestrator(exit_on_idle=True)
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

    When stdin is piped: Process those specific records and exit.
    When run standalone: Run orchestrator in foreground.
    """
    # Check if stdin has data (non-TTY means piped input)
    if not sys.stdin.isatty():
        sys.exit(process_stdin_records())
    else:
        sys.exit(run_orchestrator(daemon=daemon))


if __name__ == '__main__':
    main()
