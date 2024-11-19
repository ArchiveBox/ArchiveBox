#!/usr/bin/env python3
__package__ = 'archivebox.cli'
__command__ = 'archivebox help'

import os    
from pathlib import Path

import click
from rich import print
from rich.panel import Panel


def help() -> None:
    """Print the ArchiveBox help message and usage"""

    from archivebox.cli import ArchiveBoxGroup
    from archivebox.config import CONSTANTS
    from archivebox.config.permissions import IN_DOCKER
    from archivebox.misc.logging_util import log_cli_command
    
    log_cli_command('help', [], None, '.')
    
    COMMANDS_HELP_TEXT = '\n    '.join(
        f'[green]{cmd.ljust(20)}[/green] {ArchiveBoxGroup._lazy_load(cmd).__doc__}'
        for cmd in ArchiveBoxGroup.meta_commands.keys()
    ) + '\n\n    ' + '\n    '.join(
        f'[green]{cmd.ljust(20)}[/green] {ArchiveBoxGroup._lazy_load(cmd).__doc__}'
        for cmd in ArchiveBoxGroup.setup_commands.keys()
    ) + '\n\n    ' + '\n    '.join(
        f'[green]{cmd.ljust(20)}[/green] {ArchiveBoxGroup._lazy_load(cmd).__doc__}'
        for cmd in ArchiveBoxGroup.archive_commands.keys()
    )
    
    DOCKER_USAGE = '''
[dodger_blue3]Docker Usage:[/dodger_blue3]
    [grey53]# using Docker Compose:[/grey53]
    [blue]docker compose run[/blue] [dark_green]archivebox[/dark_green] [green]\\[command][/green] [green3][...args][/green3] [violet][--help][/violet] [grey53][--version][/grey53]

    [grey53]# using Docker:[/grey53]
    [blue]docker run[/blue] -v [light_slate_blue]$PWD:/data[/light_slate_blue] [grey53]-p 8000:8000[/grey53] -it [dark_green]archivebox/archivebox[/dark_green] [green]\\[command][/green] [green3][...args][/green3] [violet][--help][/violet] [grey53][--version][/grey53]
''' if IN_DOCKER else ''
    DOCKER_DOCS = '\n    [link=https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#usage]https://github.com/ArchiveBox/ArchiveBox/wiki/Docker[/link]' if IN_DOCKER else ''
    DOCKER_OUTSIDE_HINT = "\n    [grey53]# outside of Docker:[/grey53]" if IN_DOCKER else ''
    DOCKER_CMD_PREFIX = "[blue]docker ... [/blue]" if IN_DOCKER else ''

    print(f'''{DOCKER_USAGE}
[deep_sky_blue4]Usage:[/deep_sky_blue4]{DOCKER_OUTSIDE_HINT}
    [dark_green]archivebox[/dark_green] [green]\\[command][/green] [green3][...args][/green3] [violet][--help][/violet] [grey53][--version][/grey53]

[deep_sky_blue4]Commands:[/deep_sky_blue4]
    {COMMANDS_HELP_TEXT}

[deep_sky_blue4]Documentation:[/deep_sky_blue4]
    [link=https://github.com/ArchiveBox/ArchiveBox/wiki]https://github.com/ArchiveBox/ArchiveBox/wiki[/link]{DOCKER_DOCS}
    [link=https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#cli-usage]https://github.com/ArchiveBox/ArchiveBox/wiki/Usage[/link]
    [link=https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration]https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration[/link]
''')
    
    
    if os.access(CONSTANTS.ARCHIVE_DIR, os.R_OK) and CONSTANTS.ARCHIVE_DIR.is_dir():
        pretty_out_dir = str(CONSTANTS.DATA_DIR).replace(str(Path('~').expanduser()), '~')
        EXAMPLE_USAGE = f'''
[light_slate_blue]DATA DIR[/light_slate_blue]: [yellow]{pretty_out_dir}[/yellow]

[violet]Hint:[/violet] [i]Common maintenance tasks:[/i]
    [dark_green]archivebox[/dark_green] [green]init[/green]      [grey53]# make sure database is up-to-date (safe to run multiple times)[/grey53]
    [dark_green]archivebox[/dark_green] [green]install[/green]   [grey53]# make sure plugins are up-to-date (wget, chrome, singlefile, etc.)[/grey53]
    [dark_green]archivebox[/dark_green] [green]status[/green]    [grey53]# get a health checkup report on your collection[/grey53]
    [dark_green]archivebox[/dark_green] [green]update[/green]    [grey53]# retry any previously failed or interrupted archiving tasks[/grey53]

[violet]Hint:[/violet] [i]More example usage:[/i]
    [dark_green]archivebox[/dark_green] [green]add[/green] --depth=1 "https://example.com/some/page"
    [dark_green]archivebox[/dark_green] [green]list[/green] --sort=timestamp --csv=timestamp,downloaded_at,url,title
    [dark_green]archivebox[/dark_green] [green]schedule[/green] --every=day --depth=1 "https://example.com/some/feed.rss"
    [dark_green]archivebox[/dark_green] [green]server[/green] [blue]0.0.0.0:8000[/blue]                [grey53]# Start the Web UI / API server[/grey53]
'''
        print(Panel(EXAMPLE_USAGE, expand=False, border_style='grey53', title='[green3]:white_check_mark: A collection [light_slate_blue]DATA DIR[/light_slate_blue] is currently active[/green3]', subtitle='Commands run inside this dir will only apply to this collection.'))
    else:
        DATA_SETUP_HELP = '\n'
        if IN_DOCKER:
            DATA_SETUP_HELP += '[violet]Hint:[/violet] When using Docker, you need to mount a volume to use as your data dir:\n'
            DATA_SETUP_HELP += '    docker run [violet]-v /some/path/data:/data[/violet] archivebox/archivebox ...\n\n'
        DATA_SETUP_HELP += 'To load an [dark_blue]existing[/dark_blue] collection:\n'
        DATA_SETUP_HELP += '    1. [green]cd[/green] ~/archivebox/data     [grey53]# go into existing [light_slate_blue]DATA DIR[/light_slate_blue] (can be anywhere)[/grey53]\n'
        DATA_SETUP_HELP += f'    2. {DOCKER_CMD_PREFIX}[dark_green]archivebox[/dark_green] [green]init[/green]          [grey53]# migrate to latest version (safe to run multiple times)[/grey53]\n'
        DATA_SETUP_HELP += f'    3. {DOCKER_CMD_PREFIX}[dark_green]archivebox[/dark_green] [green]install[/green]       [grey53]# auto-update all plugins (wget, chrome, singlefile, etc.)[/grey53]\n'
        DATA_SETUP_HELP += f'    4. {DOCKER_CMD_PREFIX}[dark_green]archivebox[/dark_green] [green]help[/green]          [grey53]# ...get help with next steps... [/grey53]\n\n'
        DATA_SETUP_HELP += 'To start a [sea_green1]new[/sea_green1] collection:\n'
        DATA_SETUP_HELP += '    1. [green]mkdir[/green] ~/archivebox/data  [grey53]# create a new, empty [light_slate_blue]DATA DIR[/light_slate_blue] (can be anywhere)[/grey53]\n'
        DATA_SETUP_HELP += '    2. [green]cd[/green] ~/archivebox/data     [grey53]# cd into the new directory[/grey53]\n'
        DATA_SETUP_HELP += f'    3. {DOCKER_CMD_PREFIX}[dark_green]archivebox[/dark_green] [green]init[/green]          [grey53]# initialize ArchiveBox in the new data dir[/grey53]\n'
        DATA_SETUP_HELP += f'    4. {DOCKER_CMD_PREFIX}[dark_green]archivebox[/dark_green] [green]install[/green]       [grey53]# auto-install all plugins (wget, chrome, singlefile, etc.)[/grey53]\n'
        DATA_SETUP_HELP += f'    5. {DOCKER_CMD_PREFIX}[dark_green]archivebox[/dark_green] [green]help[/green]          [grey53]# ... get help with next steps... [/grey53]\n'
        print(Panel(DATA_SETUP_HELP, expand=False, border_style='grey53', title='[red]:cross_mark: No collection is currently active[/red]', subtitle='All archivebox [green]commands[/green] should be run from inside a collection [light_slate_blue]DATA DIR[/light_slate_blue]'))



@click.command()
@click.option('--help', '-h', is_flag=True, help='Show help')
def main(**kwargs):
    """Print the ArchiveBox help message and usage"""
    return help()

if __name__ == '__main__':
    main()
