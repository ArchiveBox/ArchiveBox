#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox snapshot'

import sys

import rich_click as click

from archivebox.cli.archivebox_snapshot import create_snapshots


@click.command(context_settings={'ignore_unknown_options': True})
@click.option('--tag', '-t', default='', help='Comma-separated tags to add')
@click.option('--status', '-s', default='queued', help='Initial status (default: queued)')
@click.option('--depth', '-d', type=int, default=0, help='Crawl depth (default: 0)')
@click.argument('urls', nargs=-1)
def main(tag: str, status: str, depth: int, urls: tuple[str, ...]):
    """Backwards-compatible `archivebox snapshot URL...` entrypoint."""
    sys.exit(create_snapshots(urls, tag=tag, status=status, depth=depth))


if __name__ == '__main__':
    main()
