#!/usr/bin/env python3

"""
archivebox orchestrator [--daemon]

Start the orchestrator process that manages workers.

The orchestrator polls queues for each model type (Crawl, Snapshot, ArchiveResult)
and lazily spawns worker processes when there is work to be done.
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox orchestrator'

import sys

import rich_click as click

from archivebox.misc.util import docstring


def orchestrator(daemon: bool = False, watch: bool = False) -> int:
    """
    Start the orchestrator process.
    
    The orchestrator:
    1. Polls each model queue (Crawl, Snapshot, ArchiveResult)
    2. Spawns worker processes when there is work to do
    3. Monitors worker health and restarts failed workers
    4. Exits when all queues are empty (unless --daemon)
    
    Args:
        daemon: Run forever (don't exit when idle)
        watch: Just watch the queues without spawning workers (for debugging)
    
    Exit codes:
        0: All work completed successfully
        1: Error occurred
    """
    from archivebox.workers.orchestrator import Orchestrator
    
    if Orchestrator.is_running():
        print('[yellow]Orchestrator is already running[/yellow]')
        return 0
    
    try:
        orchestrator_instance = Orchestrator(exit_on_idle=not daemon)
        orchestrator_instance.runloop()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f'[red]Orchestrator error: {type(e).__name__}: {e}[/red]', file=sys.stderr)
        return 1


@click.command()
@click.option('--daemon', '-d', is_flag=True, help="Run forever (don't exit on idle)")
@click.option('--watch', '-w', is_flag=True, help="Watch queues without spawning workers")
@docstring(orchestrator.__doc__)
def main(daemon: bool, watch: bool):
    """Start the ArchiveBox orchestrator process"""
    sys.exit(orchestrator(daemon=daemon, watch=watch))


if __name__ == '__main__':
    main()
