#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox worker'

import sys
import json

import rich_click as click


@click.command()
@click.argument('worker_type')
@click.option('--wait-for-first-event', is_flag=True)
@click.option('--exit-on-idle', is_flag=True)
def main(worker_type: str, wait_for_first_event: bool, exit_on_idle: bool):
    """Start an ArchiveBox worker process of the given type"""
    
    from workers.worker import get_worker_type
    
    # allow piping in events to process from stdin
    # if not sys.stdin.isatty():
    #     for line in sys.stdin.readlines():
    #         Event.dispatch(event=json.loads(line), parent=None)

    # run the actor
    Worker = get_worker_type(worker_type)
    for event in Worker.run(wait_for_first_event=wait_for_first_event, exit_on_idle=exit_on_idle):
        print(event)


if __name__ == '__main__':
    main()
