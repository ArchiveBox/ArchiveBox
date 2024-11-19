#!/usr/bin/env python3

__package__ = 'archivebox.cli'

from typing import Iterable

import rich_click as click

from archivebox.misc.util import docstring


def shell(args: Iterable[str]=()) -> None:
    """Enter an interactive ArchiveBox Django shell"""

    from django.core.management import call_command
    call_command("shell_plus", *args)


@click.command(add_help_option=False, context_settings=dict(ignore_unknown_options=True))
@click.argument('args', nargs=-1)
@docstring(shell.__doc__)
def main(args: Iterable[str]=()) -> None:
    shell(args=args)


if __name__ == '__main__':
    main()
