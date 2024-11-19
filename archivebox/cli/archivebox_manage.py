#!/usr/bin/env python3

__package__ = 'archivebox.cli'

import rich_click as click
from archivebox.misc.util import docstring, enforce_types


@enforce_types
def manage(args: list[str] | None=None) -> None:
    """Run an ArchiveBox Django management command"""

    from archivebox.config.common import SHELL_CONFIG
    from archivebox.misc.logging import stderr

    if (args and "createsuperuser" in args) and (SHELL_CONFIG.IN_DOCKER and not SHELL_CONFIG.IS_TTY):
        stderr('[!] Warning: you need to pass -it to use interactive commands in docker', color='lightyellow')
        stderr('    docker run -it archivebox manage {}'.format(' '.join(args or ['...'])), color='lightyellow')
        stderr('')

    from django.core.management import execute_from_command_line
    execute_from_command_line(['manage.py', *(args or ['help'])])


@click.command(add_help_option=False, context_settings=dict(ignore_unknown_options=True))
@click.argument('args', nargs=-1)
@docstring(manage.__doc__)
def main(args: list[str] | None=None) -> None:
    manage(args=args)


if __name__ == '__main__':
    main()
