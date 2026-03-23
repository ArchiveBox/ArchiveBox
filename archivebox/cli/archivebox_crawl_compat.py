#!/usr/bin/env python3

__package__ = "archivebox.cli"
__command__ = "archivebox crawl"

import sys

import rich_click as click

from archivebox.cli.archivebox_add import add


@click.command(context_settings={"ignore_unknown_options": True})
@click.option("--depth", "-d", type=int, default=0, help="Max crawl depth (default: 0)")
@click.option("--tag", "-t", default="", help="Comma-separated tags to add")
@click.option("--status", "-s", default="queued", help="Initial status (default: queued)")
@click.option("--wait/--no-wait", "wait", default=True, help="Accepted for backwards compatibility")
@click.argument("urls", nargs=-1)
def main(depth: int, tag: str, status: str, wait: bool, urls: tuple[str, ...]):
    """Backwards-compatible `archivebox crawl URL...` entrypoint."""
    del status, wait
    add(list(urls), depth=depth, tag=tag, index_only=True, bg=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
