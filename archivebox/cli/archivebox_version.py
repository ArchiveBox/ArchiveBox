#!/usr/bin/env python3

__package__ = 'archivebox.cli'

import sys
import os
import platform
from pathlib import Path
from typing import Iterable, Optional

import rich_click as click

from archivebox.misc.util import docstring, enforce_types


@enforce_types
def version(quiet: bool=False,
            binaries: Iterable[str]=()) -> list[str]:
    """Print the ArchiveBox version, debug metadata, and installed dependency versions"""
    
    # fast path for just getting the version and exiting, dont do any slower imports
    from archivebox.config.version import VERSION
    print(VERSION)
    if quiet or '--version' in sys.argv:
        return []
    
    from rich.panel import Panel
    from rich.console import Console
    
    from archivebox.config import CONSTANTS, DATA_DIR
    from archivebox.config.version import get_COMMIT_HASH, get_BUILD_TIME
    from archivebox.config.permissions import ARCHIVEBOX_USER, ARCHIVEBOX_GROUP, RUNNING_AS_UID, RUNNING_AS_GID, IN_DOCKER
    from archivebox.config.paths import get_data_locations, get_code_locations
    from archivebox.config.common import SHELL_CONFIG, STORAGE_CONFIG, SEARCH_BACKEND_CONFIG
    from archivebox.misc.logging_util import printable_folder_status
    from archivebox.config.configset import get_config
    
    console = Console()
    prnt = console.print
    
    # Check if LDAP is enabled (simple config lookup)
    config = get_config()
    LDAP_ENABLED = config.get('LDAP_ENABLED', False)

    p = platform.uname()
    COMMIT_HASH = get_COMMIT_HASH()
    prnt(
        '[dark_green]ArchiveBox[/dark_green] [dark_goldenrod]v{}[/dark_goldenrod]'.format(CONSTANTS.VERSION),
        f'COMMIT_HASH={COMMIT_HASH[:7] if COMMIT_HASH else "unknown"}',
        f'BUILD_TIME={get_BUILD_TIME()}',
    )
    prnt(
        f'IN_DOCKER={IN_DOCKER}',
        f'IN_QEMU={SHELL_CONFIG.IN_QEMU}',
        f'ARCH={p.machine}',
        f'OS={p.system}',
        f'PLATFORM={platform.platform()}',
        f'PYTHON={sys.implementation.name.title()}' + (' (venv)' if CONSTANTS.IS_INSIDE_VENV else ''),
    )
    
    try:
        OUTPUT_IS_REMOTE_FS = get_data_locations().DATA_DIR.is_mount or get_data_locations().ARCHIVE_DIR.is_mount
    except Exception:
        OUTPUT_IS_REMOTE_FS = False
        
    try:
        DATA_DIR_STAT = CONSTANTS.DATA_DIR.stat()
        prnt(
            f'EUID={os.geteuid()}:{os.getegid()} UID={RUNNING_AS_UID}:{RUNNING_AS_GID} PUID={ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}',
            f'FS_UID={DATA_DIR_STAT.st_uid}:{DATA_DIR_STAT.st_gid}',
            f'FS_PERMS={STORAGE_CONFIG.OUTPUT_PERMISSIONS}',
            f'FS_ATOMIC={STORAGE_CONFIG.ENFORCE_ATOMIC_WRITES}',
            f'FS_REMOTE={OUTPUT_IS_REMOTE_FS}',
        )
    except Exception:
        prnt(
            f'EUID={os.geteuid()}:{os.getegid()} UID={RUNNING_AS_UID}:{RUNNING_AS_GID} PUID={ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}',
        )
        
    prnt(
        f'DEBUG={SHELL_CONFIG.DEBUG}',
        f'IS_TTY={SHELL_CONFIG.IS_TTY}',
        f'SUDO={CONSTANTS.IS_ROOT}',
        f'ID={CONSTANTS.MACHINE_ID}:{CONSTANTS.COLLECTION_ID}',
        f'SEARCH_BACKEND={SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_ENGINE}',
        f'LDAP={LDAP_ENABLED}',
    )
    prnt()
    
    if not (os.access(CONSTANTS.ARCHIVE_DIR, os.R_OK) and os.access(CONSTANTS.CONFIG_FILE, os.R_OK)):
        PANEL_TEXT = '\n'.join((
            '',
            '[violet]Hint:[/violet] [green]cd[/green] into a collection [blue]DATA_DIR[/blue] and run [green]archivebox version[/green] again...',
            '      [grey53]OR[/grey53] run [green]archivebox init[/green] to create a new collection in the current dir.',
            '',
            '      [i][grey53](this is [red]REQUIRED[/red] if you are opening a Github Issue to get help)[/grey53][/i]',
            '',
        ))
        prnt(Panel(PANEL_TEXT, expand=False, border_style='grey53', title='[red]:exclamation: No collection [blue]DATA_DIR[/blue] is currently active[/red]', subtitle='Full version info is only available when inside a collection [light_slate_blue]DATA DIR[/light_slate_blue]'))
        prnt()
        return []

    prnt('[pale_green1][i] Binary Dependencies:[/pale_green1]')
    failures = []

    # Setup Django before importing models
    try:
        from archivebox.config.django import setup_django
        setup_django()

        from archivebox.machine.models import Machine, Binary

        machine = Machine.current()

        # Get all binaries from the database with timeout protection
        all_installed = Binary.objects.filter(
            machine=machine
        ).exclude(abspath='').exclude(abspath__isnull=True).order_by('name')

        if not all_installed.exists():
            prnt('', '[grey53]No binaries detected. Run [green]archivebox install[/green] to detect dependencies.[/grey53]')
        else:
            for installed in all_installed:
                # Skip if user specified specific binaries and this isn't one
                if binaries and installed.name not in binaries:
                    continue

                if installed.is_valid:
                    display_path = installed.abspath.replace(str(DATA_DIR), '.').replace(str(Path('~').expanduser()), '~')
                    version_str = (installed.version or 'unknown')[:15]
                    provider = (installed.binprovider or 'env')[:8]
                    prnt('', '[green]√[/green]', '', installed.name.ljust(18), version_str.ljust(16), provider.ljust(8), display_path, overflow='ignore', crop=False)
                else:
                    prnt('', '[red]X[/red]', '', installed.name.ljust(18), '[grey53]not installed[/grey53]', overflow='ignore', crop=False)
                    failures.append(installed.name)

        # Show hint if no binaries are installed yet
        has_any_installed = Binary.objects.filter(machine=machine).exclude(abspath='').exists()
        if not has_any_installed:
            prnt()
            prnt('', '[grey53]Run [green]archivebox install[/green] to detect and install dependencies.[/grey53]')

    except Exception as e:
        # Handle database errors gracefully (locked, missing, etc.)
        prnt()
        prnt('', f'[yellow]Warning: Could not query binaries from database: {e}[/yellow]')
        prnt('', '[grey53]Run [green]archivebox init[/green] and [green]archivebox install[/green] to set up dependencies.[/grey53]')

    if not binaries:
        # Show code and data locations
        prnt()
        prnt('[deep_sky_blue3][i] Code locations:[/deep_sky_blue3]')
        try:
            for name, path in get_code_locations().items():
                if isinstance(path, dict):
                    prnt(printable_folder_status(name, path), overflow='ignore', crop=False)
        except Exception as e:
            prnt(f'  [red]Error getting code locations: {e}[/red]')

        prnt()
        if os.access(CONSTANTS.ARCHIVE_DIR, os.R_OK) or os.access(CONSTANTS.CONFIG_FILE, os.R_OK):
            prnt('[bright_yellow][i] Data locations:[/bright_yellow]')
            try:
                for name, path in get_data_locations().items():
                    if isinstance(path, dict):
                        prnt(printable_folder_status(name, path), overflow='ignore', crop=False)
            except Exception as e:
                prnt(f'  [red]Error getting data locations: {e}[/red]')
            
            try:
                from archivebox.misc.checks import check_data_dir_permissions
                check_data_dir_permissions()
            except Exception:
                pass
        else:
            prnt()
            prnt('[red][i] Data locations:[/red] (not in a data directory)')
        
    prnt()
    
    if failures:
        prnt('[red]Error:[/red] [yellow]Failed to detect the following binaries:[/yellow]')
        prnt(f'      [red]{", ".join(failures)}[/red]')
        prnt()
        prnt('[violet]Hint:[/violet] To install missing binaries automatically, run:')
        prnt('      [green]archivebox install[/green]')
        prnt()
    return failures


@click.command()
@click.option('--quiet', '-q', is_flag=True, help='Only print ArchiveBox version number and nothing else. (equivalent to archivebox --version)')
@click.option('--binaries', '-b', help='Select binaries to detect DEFAULT=curl,wget,git,yt-dlp,chrome,single-file,readability-extractor,postlight-parser,... (all)')
@docstring(version.__doc__)
def main(**kwargs):
    failures = version(**kwargs)
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
