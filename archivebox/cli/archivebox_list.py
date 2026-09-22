#!/usr/bin/env python3

__package__ = "archivebox.cli"
__command__ = "archivebox list"

import sys

import rich_click as click

from archivebox.cli.archivebox_snapshot import list_snapshots, snapshot_filter_options, snapshot_output_options


@click.command()
@snapshot_output_options
@snapshot_filter_options(default_filter_type="substring")
def main(**kwargs) -> None:
    """List Snapshots."""
    sys.exit(list_snapshots(**kwargs))


if __name__ == "__main__":
    main()
