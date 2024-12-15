#!/usr/bin/env python3

__package__ = 'archivebox.cli'

import sys
from typing import Iterable

import rich_click as click

from archivebox.misc.util import docstring, enforce_types


@enforce_types
def version(quiet: bool=False,
            binproviders: Iterable[str]=(),
            binaries: Iterable[str]=()) -> list[str]:
    """Print the ArchiveBox version, debug metadata, and installed dependency versions"""
    
    # fast path for just getting the version and exiting, dont do any slower imports
    from archivebox.config.version import VERSION
    print(VERSION)
    if quiet or '--version' in sys.argv:
        return []
    
    # Only do slower imports when getting full version info
    import os
    import platform
    from pathlib import Path
    
    from rich.panel import Panel
    from rich.console import Console
    from abx_pkg import Binary
    
    import abx
    import archivebox
    from archivebox.config import CONSTANTS, DATA_DIR
    from archivebox.config.version import get_COMMIT_HASH, get_BUILD_TIME
    from archivebox.config.permissions import ARCHIVEBOX_USER, ARCHIVEBOX_GROUP, RUNNING_AS_UID, RUNNING_AS_GID, IN_DOCKER
    from archivebox.config.paths import get_data_locations, get_code_locations
    from archivebox.config.common import SHELL_CONFIG, STORAGE_CONFIG, SEARCH_BACKEND_CONFIG
    from archivebox.misc.logging_util import printable_folder_status
    
    from abx_plugin_default_binproviders import apt, brew, env
    
    console = Console()
    prnt = console.print
    
    LDAP_ENABLED = archivebox.pm.hook.get_SCOPE_CONFIG().LDAP_ENABLED

    # 0.7.1
    # ArchiveBox v0.7.1+editable COMMIT_HASH=951bba5 BUILD_TIME=2023-12-17 16:46:05 1702860365
    # IN_DOCKER=False IN_QEMU=False ARCH=arm64 OS=Darwin PLATFORM=macOS-14.2-arm64-arm-64bit PYTHON=Cpython
    # FS_ATOMIC=True FS_REMOTE=False FS_USER=501:20 FS_PERMS=644
    # DEBUG=False IS_TTY=True TZ=UTC SEARCH_BACKEND=ripgrep LDAP=False
    
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
    OUTPUT_IS_REMOTE_FS = get_data_locations().DATA_DIR.is_mount or get_data_locations().ARCHIVE_DIR.is_mount
    DATA_DIR_STAT = CONSTANTS.DATA_DIR.stat()
    prnt(
        f'EUID={os.geteuid()}:{os.getegid()} UID={RUNNING_AS_UID}:{RUNNING_AS_GID} PUID={ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}',
        f'FS_UID={DATA_DIR_STAT.st_uid}:{DATA_DIR_STAT.st_gid}',
        f'FS_PERMS={STORAGE_CONFIG.OUTPUT_PERMISSIONS}',
        f'FS_ATOMIC={STORAGE_CONFIG.ENFORCE_ATOMIC_WRITES}',
        f'FS_REMOTE={OUTPUT_IS_REMOTE_FS}',
    )
    prnt(
        f'DEBUG={SHELL_CONFIG.DEBUG}',
        f'IS_TTY={SHELL_CONFIG.IS_TTY}',
        f'SUDO={CONSTANTS.IS_ROOT}',
        f'ID={CONSTANTS.MACHINE_ID}:{CONSTANTS.COLLECTION_ID}',
        f'SEARCH_BACKEND={SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_ENGINE}',
        f'LDAP={LDAP_ENABLED}',
        #f'DB=django.db.backends.sqlite3 (({CONFIG["SQLITE_JOURNAL_MODE"]})',  # add this if we have more useful info to show eventually
    )
    prnt()
    
    if not (os.access(CONSTANTS.ARCHIVE_DIR, os.R_OK) and os.access(CONSTANTS.CONFIG_FILE, os.R_OK)):
        PANEL_TEXT = '\n'.join((
            # '',
            # f'[yellow]CURRENT DIR =[/yellow] [red]{os.getcwd()}[/red]',
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
    BINARIES = abx.as_dict(archivebox.pm.hook.get_BINARIES())
    for name, binary in list(BINARIES.items()):
        if binary.name == 'archivebox':
            continue
        
        # skip if the binary is not in the requested list of binaries
        if binaries and binary.name not in binaries:
            continue
        
        # skip if the binary is not supported by any of the requested binproviders
        if binproviders and binary.binproviders_supported and not any(provider.name in binproviders for provider in binary.binproviders_supported):
            continue
        
        err = None
        try:
            loaded_bin = binary.load()
        except Exception as e:
            err = e
            loaded_bin = binary
        provider_summary = f'[dark_sea_green3]{loaded_bin.binprovider.name.ljust(10)}[/dark_sea_green3]' if loaded_bin.binprovider else '[grey23]not found[/grey23] '
        if loaded_bin.abspath:
            abspath = str(loaded_bin.abspath).replace(str(DATA_DIR), '[light_slate_blue].[/light_slate_blue]').replace(str(Path('~').expanduser()), '~')
            if ' ' in abspath:
                abspath = abspath.replace(' ', r'\ ')
        else:
            abspath = f'[red]{err}[/red]'
        prnt('', '[green]√[/green]' if loaded_bin.is_valid else '[red]X[/red]', '', loaded_bin.name.ljust(21), str(loaded_bin.version).ljust(12), provider_summary, abspath, overflow='ignore', crop=False)
        if not loaded_bin.is_valid:
            failures.append(loaded_bin.name)
            
    prnt()
    prnt('[gold3][i] Package Managers:[/gold3]')
    BINPROVIDERS = abx.as_dict(archivebox.pm.hook.get_BINPROVIDERS())
    for name, binprovider in list(BINPROVIDERS.items()):
        err = None
        
        if binproviders and binprovider.name not in binproviders:
            continue
        
        # TODO: implement a BinProvider.BINARY() method that gets the loaded binary for a binprovider's INSTALLER_BIN
        loaded_bin = binprovider.INSTALLER_BINARY or Binary(name=binprovider.INSTALLER_BIN, binproviders=[env, apt, brew])
        
        abspath = str(loaded_bin.abspath).replace(str(DATA_DIR), '[light_slate_blue].[/light_slate_blue]').replace(str(Path('~').expanduser()), '~')
        abspath = None
        if loaded_bin.abspath:
            abspath = str(loaded_bin.abspath).replace(str(DATA_DIR), '.').replace(str(Path('~').expanduser()), '~')
            if ' ' in abspath:
                abspath = abspath.replace(' ', r'\ ')
                
        PATH = str(binprovider.PATH).replace(str(DATA_DIR), '[light_slate_blue].[/light_slate_blue]').replace(str(Path('~').expanduser()), '~')
        ownership_summary = f'UID=[blue]{str(binprovider.EUID).ljust(4)}[/blue]'
        provider_summary = f'[dark_sea_green3]{str(abspath).ljust(52)}[/dark_sea_green3]' if abspath else f'[grey23]{"not available".ljust(52)}[/grey23]'
        prnt('', '[green]√[/green]' if binprovider.is_valid else '[grey53]-[/grey53]', '', binprovider.name.ljust(11), provider_summary, ownership_summary, f'PATH={PATH}', overflow='ellipsis', soft_wrap=True)

    if not (binaries or binproviders):
        # dont show source code / data dir info if we just want to get version info for a binary or binprovider
        
        prnt()
        prnt('[deep_sky_blue3][i] Code locations:[/deep_sky_blue3]')
        for name, path in get_code_locations().items():
            prnt(printable_folder_status(name, path), overflow='ignore', crop=False)

        prnt()
        if os.access(CONSTANTS.ARCHIVE_DIR, os.R_OK) or os.access(CONSTANTS.CONFIG_FILE, os.R_OK):
            prnt('[bright_yellow][i] Data locations:[/bright_yellow]')
            for name, path in get_data_locations().items():
                prnt(printable_folder_status(name, path), overflow='ignore', crop=False)
        
            from archivebox.misc.checks import check_data_dir_permissions
            
            check_data_dir_permissions()
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
@click.option('--binproviders', '-p', help='Select binproviders to detect DEFAULT=env,apt,brew,sys_pip,venv_pip,lib_pip,pipx,sys_npm,lib_npm,puppeteer,playwright (all)')
@click.option('--binaries', '-b', help='Select binaries to detect DEFAULT=curl,wget,git,yt-dlp,chrome,single-file,readability-extractor,postlight-parser,... (all)')
@docstring(version.__doc__)
def main(**kwargs):
    failures = version(**kwargs)
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
