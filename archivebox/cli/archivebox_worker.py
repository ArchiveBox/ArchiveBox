#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox worker'

import sys

import rich_click as click

from archivebox.misc.util import docstring


def worker(worker_type: str, daemon: bool = False, plugin: str | None = None):
    """
    Start a worker process to process items from the queue.

    Worker types:
        - crawl: Process Crawl objects (parse seeds, create snapshots)
        - snapshot: Process Snapshot objects (create archive results)
        - archiveresult: Process ArchiveResult objects (run plugins)

    Workers poll the database for queued items, claim them atomically,
    and spawn subprocess tasks to handle each item.
    """
    from workers.worker import get_worker_class

    WorkerClass = get_worker_class(worker_type)

    # Build kwargs
    kwargs = {'daemon': daemon}
    if plugin and worker_type == 'archiveresult':
        kwargs['extractor'] = plugin  # internal field still called extractor

    # Create and run worker
    worker_instance = WorkerClass(**kwargs)
    worker_instance.runloop()


@click.command()
@click.argument('worker_type', type=click.Choice(['crawl', 'snapshot', 'archiveresult']))
@click.option('--daemon', '-d', is_flag=True, help="Run forever (don't exit on idle)")
@click.option('--plugin', '-p', default=None, help='Filter by plugin (archiveresult only)')
@docstring(worker.__doc__)
def main(worker_type: str, daemon: bool, plugin: str | None):
    """Start an ArchiveBox worker process"""
    worker(worker_type, daemon=daemon, plugin=plugin)


if __name__ == '__main__':
    main()
