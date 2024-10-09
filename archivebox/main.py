__package__ = 'archivebox'

import os
import sys
import shutil
import platform

from typing import Dict, List, Optional, Iterable, IO, Union
from pathlib import Path
from datetime import date, datetime

from crontab import CronTab, CronSlices

from django.db.models import QuerySet
from django.utils import timezone

from archivebox.config import CONSTANTS, VERSION, DATA_DIR, ARCHIVE_DIR
from archivebox.config.common import SHELL_CONFIG, SEARCH_BACKEND_CONFIG, STORAGE_CONFIG, SERVER_CONFIG, ARCHIVING_CONFIG
from archivebox.config.permissions import SudoPermission, IN_DOCKER
from .cli import (
    CLI_SUBCOMMANDS,
    run_subcommand,
    display_first,
    meta_cmds,
    setup_cmds,
    archive_cmds,
)
from .parsers import (
    save_text_as_source,
    save_file_as_source,
    parse_links_memory,
)
from archivebox.misc.util import enforce_types                         # type: ignore
from archivebox.misc.system import get_dir_size, dedupe_cron_jobs, CRON_COMMENT
from archivebox.misc.system import run as run_shell
from .index.schema import Link
from .index import (
    load_main_index,
    parse_links_from_source,
    dedupe_links,
    write_main_index,
    snapshot_filter,
    get_indexed_folders,
    get_archived_folders,
    get_unarchived_folders,
    get_present_folders,
    get_valid_folders,
    get_invalid_folders,
    get_duplicate_folders,
    get_orphaned_folders,
    get_corrupted_folders,
    get_unrecognized_folders,
    fix_invalid_folder_locations,
    write_link_details,
)
from .index.json import (
    parse_json_main_index,
    parse_json_links_details,
    generate_json_index_from_links,
)
from .index.sql import (
    get_admins,
    apply_migrations,
    remove_from_sql_main_index,
)
from .index.html import generate_index_from_links
from .index.csv import links_to_csv
from .extractors import archive_links, archive_link, ignore_methods
from archivebox.misc.logging import stderr, hint
from archivebox.misc.checks import check_data_folder
from archivebox.config.legacy import (
    write_config_file,
    load_all_config,
    get_real_name,
)
from .logging_util import (
    TimedProgress,
    log_importing_started,
    log_crawl_started,
    log_removal_started,
    log_removal_finished,
    log_list_started,
    log_list_finished,
    printable_config,
    printable_folders,
    printable_filesize,
    printable_folder_status,
)


@enforce_types
def help(out_dir: Path=DATA_DIR) -> None:
    """Print the ArchiveBox help message and usage"""

    from rich import print
    from rich.panel import Panel

    all_subcommands = CLI_SUBCOMMANDS
    COMMANDS_HELP_TEXT = '\n    '.join(
        f'[green]{cmd.ljust(20)}[/green] {func.__doc__}'
        for cmd, func in all_subcommands.items()
        if cmd in meta_cmds
    ) + '\n\n    ' + '\n    '.join(
        f'[green]{cmd.ljust(20)}[/green] {func.__doc__}'
        for cmd, func in all_subcommands.items()
        if cmd in setup_cmds
    ) + '\n\n    ' + '\n    '.join(
        f'[green]{cmd.ljust(20)}[/green] {func.__doc__}'
        for cmd, func in all_subcommands.items()
        if cmd in archive_cmds
    ) + '\n\n    ' + '\n    '.join(
        f'[green]{cmd.ljust(20)}[/green] {func.__doc__}'
        for cmd, func in all_subcommands.items()
        if cmd not in display_first
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
        pretty_out_dir = str(out_dir).replace(str(Path('~').expanduser()), '~')
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


@enforce_types
def version(quiet: bool=False,
            out_dir: Path=DATA_DIR) -> None:
    """Print the ArchiveBox version and dependency information"""
    
    print(VERSION)
    if quiet or '--version' in sys.argv:
        return
    
    from rich.console import Console
    console = Console()
    prnt = console.print
    
    from plugins_auth.ldap.apps import LDAP_CONFIG
    from django.conf import settings
    from archivebox.config.version import get_COMMIT_HASH, get_BUILD_TIME
    from archivebox.config.permissions import ARCHIVEBOX_USER, ARCHIVEBOX_GROUP, RUNNING_AS_UID, RUNNING_AS_GID

    from abx.archivebox.base_binary import BaseBinary, apt, brew, env

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
    OUTPUT_IS_REMOTE_FS = CONSTANTS.DATA_LOCATIONS.DATA_DIR.is_mount or CONSTANTS.DATA_LOCATIONS.ARCHIVE_DIR.is_mount
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
        f'LDAP={LDAP_CONFIG.LDAP_ENABLED}',
        #f'DB=django.db.backends.sqlite3 (({CONFIG["SQLITE_JOURNAL_MODE"]})',  # add this if we have more useful info to show eventually
    )
    prnt()

    prnt('[pale_green1][i] Binary Dependencies:[/pale_green1]')
    failures = []
    for name, binary in reversed(list(settings.BINARIES.items())):
        if binary.name == 'archivebox':
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
    for name, binprovider in reversed(list(settings.BINPROVIDERS.items())):
        err = None
        
        # TODO: implement a BinProvider.BINARY() method that gets the loaded binary for a binprovider's INSTALLER_BIN
        loaded_bin = binprovider.INSTALLER_BINARY or BaseBinary(name=binprovider.INSTALLER_BIN, binproviders=[env, apt, brew])
        
        abspath = None
        if loaded_bin.abspath:
            abspath = str(loaded_bin.abspath).replace(str(DATA_DIR), '.').replace(str(Path('~').expanduser()), '~')
            if ' ' in abspath:
                abspath = abspath.replace(' ', r'\ ')
                
        PATH = str(binprovider.PATH).replace(str(DATA_DIR), '[light_slate_blue].[/light_slate_blue]').replace(str(Path('~').expanduser()), '~')
        ownership_summary = f'UID=[blue]{str(binprovider.EUID).ljust(4)}[/blue]'
        provider_summary = f'[dark_sea_green3]{str(abspath).ljust(52)}[/dark_sea_green3]' if abspath else f'[grey23]{"not available".ljust(52)}[/grey23]'
        prnt('', '[green]√[/green]' if binprovider.is_valid else '[red]X[/red]', '', binprovider.name.ljust(11), provider_summary, ownership_summary, f'PATH={PATH}', overflow='ellipsis', soft_wrap=True)

    prnt()
    prnt('[deep_sky_blue3][i] Source-code locations:[/deep_sky_blue3]')
    for name, path in CONSTANTS.CODE_LOCATIONS.items():
        prnt(printable_folder_status(name, path), overflow='ignore', crop=False)

    prnt()
    if os.access(CONSTANTS.ARCHIVE_DIR, os.R_OK) or os.access(CONSTANTS.CONFIG_FILE, os.R_OK):
        prnt('[bright_yellow][i] Data locations:[/bright_yellow]')
        for name, path in CONSTANTS.DATA_LOCATIONS.items():
            prnt(printable_folder_status(name, path), overflow='ignore', crop=False)
    
        from archivebox.misc.checks import check_data_dir_permissions
        
        check_data_dir_permissions()
    else:
        prnt()
        prnt('[red][i] Data locations:[/red] (not in a data directory)')
        
    prnt()
    
    if failures:
        raise SystemExit(1)
    raise SystemExit(0)

@enforce_types
def run(subcommand: str,
        subcommand_args: Optional[List[str]],
        stdin: Optional[IO]=None,
        out_dir: Path=DATA_DIR) -> None:
    """Run a given ArchiveBox subcommand with the given list of args"""
    run_subcommand(
        subcommand=subcommand,
        subcommand_args=subcommand_args,
        stdin=stdin,
        pwd=out_dir,
    )


@enforce_types
def init(force: bool=False, quick: bool=False, install: bool=False, out_dir: Path=DATA_DIR) -> None:
    """Initialize a new ArchiveBox collection in the current directory"""
    
    from core.models import Snapshot
    from rich import print

    out_dir.mkdir(exist_ok=True)
    is_empty = not len(set(os.listdir(out_dir)) - CONSTANTS.ALLOWED_IN_DATA_DIR)

    if os.access(out_dir / CONSTANTS.JSON_INDEX_FILENAME, os.F_OK):
        print("[red]:warning: This folder contains a JSON index. It is deprecated, and will no longer be kept up to date automatically.[/red]", file=sys.stderr)
        print("[red]    You can run `archivebox list --json --with-headers > static_index.json` to manually generate it.[/red]", file=sys.stderr)

    existing_index = os.access(CONSTANTS.DATABASE_FILE, os.F_OK)

    if is_empty and not existing_index:
        print(f'[turquoise4][+] Initializing a new ArchiveBox v{VERSION} collection...[/turquoise4]')
        print('[green]----------------------------------------------------------------------[/green]')
    elif existing_index:
        # TODO: properly detect and print the existing version in current index as well
        print(f'[green][*] Verifying and updating existing ArchiveBox collection to v{VERSION}...[/green]')
        print('[green]----------------------------------------------------------------------[/green]')
    else:
        if force:
            print('[red][!] This folder appears to already have files in it, but no index.sqlite3 is present.[/red]')
            print('[red]    Because --force was passed, ArchiveBox will initialize anyway (which may overwrite existing files).[/red]')
        else:
            print(
                ("[red][X] This folder appears to already have files in it, but no index.sqlite3 present.[/red]\n\n"
                "    You must run init in a completely empty directory, or an existing data folder.\n\n"
                "    [violet]Hint:[/violet] To import an existing data folder make sure to cd into the folder first, \n"
                "    then run and run 'archivebox init' to pick up where you left off.\n\n"
                "    (Always make sure your data folder is backed up first before updating ArchiveBox)"
                )
            )
            raise SystemExit(2)

    if existing_index:
        print('\n[green][*] Verifying archive folder structure...[/green]')
    else:
        print('\n[green][+] Building archive folder structure...[/green]')
    
    print(f'    + ./{CONSTANTS.ARCHIVE_DIR.relative_to(DATA_DIR)}, ./{CONSTANTS.SOURCES_DIR.relative_to(DATA_DIR)}, ./{CONSTANTS.LOGS_DIR.relative_to(DATA_DIR)}...')
    Path(CONSTANTS.SOURCES_DIR).mkdir(exist_ok=True)
    Path(CONSTANTS.ARCHIVE_DIR).mkdir(exist_ok=True)
    Path(CONSTANTS.LOGS_DIR).mkdir(exist_ok=True)
    print(f'    + ./{CONSTANTS.CONFIG_FILE.relative_to(DATA_DIR)}...')
    write_config_file({}, out_dir=str(out_dir))

    if os.access(CONSTANTS.DATABASE_FILE, os.F_OK):
        print('\n[green][*] Verifying main SQL index and running any migrations needed...[/green]')
    else:
        print('\n[green][+] Building main SQL index and running initial migrations...[/green]')
    
    for migration_line in apply_migrations(out_dir):
        sys.stdout.write(f'    {migration_line}\n')

    assert os.access(CONSTANTS.DATABASE_FILE, os.R_OK)
    print()
    print(f'    √ ./{CONSTANTS.DATABASE_FILE.relative_to(DATA_DIR)}')
    
    # from django.contrib.auth.models import User
    # if SHELL_CONFIG.IS_TTY and not User.objects.filter(is_superuser=True).exists():
    #     print('{green}[+] Creating admin user account...{reset}'.format(**SHELL_CONFIG.ANSI))
    #     call_command("createsuperuser", interactive=True)

    print()
    print('[dodger_blue3][*] Checking links from indexes and archive folders (safe to Ctrl+C)...[/dodger_blue3]')

    all_links = Snapshot.objects.none()
    pending_links: Dict[str, Link] = {}

    if existing_index:
        all_links = load_main_index(out_dir=out_dir, warn=False)
        print(f'    √ Loaded {all_links.count()} links from existing main index.')

    if quick:
        print('    > Skipping full snapshot directory check (quick mode)')
    else:
        try:
            # Links in data folders that dont match their timestamp
            fixed, cant_fix = fix_invalid_folder_locations(out_dir=out_dir)
            if fixed:
                print(f'    [yellow]√ Fixed {len(fixed)} data directory locations that didn\'t match their link timestamps.[/yellow]')
            if cant_fix:
                print(f'    [red]! Could not fix {len(cant_fix)} data directory locations due to conflicts with existing folders.[/red]')

            # Links in JSON index but not in main index
            orphaned_json_links = {
                link.url: link
                for link in parse_json_main_index(out_dir)
                if not all_links.filter(url=link.url).exists()
            }
            if orphaned_json_links:
                pending_links.update(orphaned_json_links)
                print(f'    [yellow]√ Added {len(orphaned_json_links)} orphaned links from existing JSON index...[/yellow]')

            # Links in data dir indexes but not in main index
            orphaned_data_dir_links = {
                link.url: link
                for link in parse_json_links_details(out_dir)
                if not all_links.filter(url=link.url).exists()
            }
            if orphaned_data_dir_links:
                pending_links.update(orphaned_data_dir_links)
                print(f'    [yellow]√ Added {len(orphaned_data_dir_links)} orphaned links from existing archive directories.[/yellow]')

            # Links in invalid/duplicate data dirs
            invalid_folders = {
                folder: link
                for folder, link in get_invalid_folders(all_links, out_dir=out_dir).items()
            }
            if invalid_folders:
                print(f'    [red]! Skipped adding {len(invalid_folders)} invalid link data directories.[/red]')
                print('        X ' + '\n        X '.join(f'./{Path(folder).relative_to(DATA_DIR)} {link}' for folder, link in invalid_folders.items()))
                print()
                print('    [violet]Hint:[/violet] For more information about the link data directories that were skipped, run:')
                print('        archivebox status')
                print('        archivebox list --status=invalid')

        except (KeyboardInterrupt, SystemExit):
            print(file=sys.stderr)
            print('[yellow]:stop_sign: Stopped checking archive directories due to Ctrl-C/SIGTERM[/yellow]', file=sys.stderr)
            print('    Your archive data is safe, but you should re-run `archivebox init` to finish the process later.', file=sys.stderr)
            print(file=sys.stderr)
            print('    [violet]Hint:[/violet] In the future you can run a quick init without checking dirs like so:', file=sys.stderr)
            print('        archivebox init --quick', file=sys.stderr)
            raise SystemExit(1)
        
        write_main_index(list(pending_links.values()), out_dir=out_dir)

    print('\n[green]----------------------------------------------------------------------[/green]')

    from django.contrib.auth.models import User

    if (SERVER_CONFIG.ADMIN_USERNAME and SERVER_CONFIG.ADMIN_PASSWORD) and not User.objects.filter(username=SERVER_CONFIG.ADMIN_USERNAME).exists():
        print('[green][+] Found ADMIN_USERNAME and ADMIN_PASSWORD configuration options, creating new admin user.[/green]')
        User.objects.create_superuser(username=SERVER_CONFIG.ADMIN_USERNAME, password=SERVER_CONFIG.ADMIN_PASSWORD)

    if existing_index:
        print('[green][√] Done. Verified and updated the existing ArchiveBox collection.[/green]')
    else:
        print(f'[green][√] Done. A new ArchiveBox collection was initialized ({len(all_links) + len(pending_links)} links).[/green]')

    json_index = out_dir / CONSTANTS.JSON_INDEX_FILENAME
    html_index = out_dir / CONSTANTS.HTML_INDEX_FILENAME
    index_name = f"{date.today()}_index_old"
    if os.access(json_index, os.F_OK):
        json_index.rename(f"{index_name}.json")
    if os.access(html_index, os.F_OK):
        html_index.rename(f"{index_name}.html")
    
    CONSTANTS.PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
    CONSTANTS.TMP_DIR.mkdir(parents=True, exist_ok=True)
    CONSTANTS.LIB_DIR.mkdir(parents=True, exist_ok=True)

    if install:
        run_subcommand('install', pwd=out_dir)

    if Snapshot.objects.count() < 25:     # hide the hints for experienced users
        print()
        print('    [violet]Hint:[/violet] To view your archive index, run:')
        print('        archivebox server  # then visit [deep_sky_blue4][link=http://127.0.0.1:8000]http://127.0.0.1:8000[/link][/deep_sky_blue4]')
        print()
        print('    To add new links, you can run:')
        print("        archivebox add < ~/some/path/to/list_of_links.txt")
        print()
        print('    For more usage and examples, run:')
        print('        archivebox help')

@enforce_types
def status(out_dir: Path=DATA_DIR) -> None:
    """Print out some info and statistics about the archive collection"""

    check_data_folder()

    from core.models import Snapshot
    from django.contrib.auth import get_user_model
    User = get_user_model()

    print('{green}[*] Scanning archive main index...{reset}'.format(**SHELL_CONFIG.ANSI))
    print(SHELL_CONFIG.ANSI['lightyellow'], f'   {out_dir}/*', SHELL_CONFIG.ANSI['reset'])
    num_bytes, num_dirs, num_files = get_dir_size(out_dir, recursive=False, pattern='index.')
    size = printable_filesize(num_bytes)
    print(f'    Index size: {size} across {num_files} files')
    print()

    links = load_main_index(out_dir=out_dir)
    num_sql_links = links.count()
    num_link_details = sum(1 for link in parse_json_links_details(out_dir=out_dir))
    print(f'    > SQL Main Index: {num_sql_links} links'.ljust(36), f'(found in {CONSTANTS.SQL_INDEX_FILENAME})')
    print(f'    > JSON Link Details: {num_link_details} links'.ljust(36), f'(found in {ARCHIVE_DIR.name}/*/index.json)')
    print()
    print('{green}[*] Scanning archive data directories...{reset}'.format(**SHELL_CONFIG.ANSI))
    print(SHELL_CONFIG.ANSI['lightyellow'], f'   {ARCHIVE_DIR}/*', SHELL_CONFIG.ANSI['reset'])
    num_bytes, num_dirs, num_files = get_dir_size(ARCHIVE_DIR)
    size = printable_filesize(num_bytes)
    print(f'    Size: {size} across {num_files} files in {num_dirs} directories')
    print(SHELL_CONFIG.ANSI['black'])
    num_indexed = len(get_indexed_folders(links, out_dir=out_dir))
    num_archived = len(get_archived_folders(links, out_dir=out_dir))
    num_unarchived = len(get_unarchived_folders(links, out_dir=out_dir))
    print(f'    > indexed: {num_indexed}'.ljust(36), f'({get_indexed_folders.__doc__})')
    print(f'      > archived: {num_archived}'.ljust(36), f'({get_archived_folders.__doc__})')
    print(f'      > unarchived: {num_unarchived}'.ljust(36), f'({get_unarchived_folders.__doc__})')
    
    num_present = len(get_present_folders(links, out_dir=out_dir))
    num_valid = len(get_valid_folders(links, out_dir=out_dir))
    print()
    print(f'    > present: {num_present}'.ljust(36), f'({get_present_folders.__doc__})')
    print(f'      > valid: {num_valid}'.ljust(36), f'({get_valid_folders.__doc__})')
    
    duplicate = get_duplicate_folders(links, out_dir=out_dir)
    orphaned = get_orphaned_folders(links, out_dir=out_dir)
    corrupted = get_corrupted_folders(links, out_dir=out_dir)
    unrecognized = get_unrecognized_folders(links, out_dir=out_dir)
    num_invalid = len({**duplicate, **orphaned, **corrupted, **unrecognized})
    print(f'      > invalid: {num_invalid}'.ljust(36), f'({get_invalid_folders.__doc__})')
    print(f'        > duplicate: {len(duplicate)}'.ljust(36), f'({get_duplicate_folders.__doc__})')
    print(f'        > orphaned: {len(orphaned)}'.ljust(36), f'({get_orphaned_folders.__doc__})')
    print(f'        > corrupted: {len(corrupted)}'.ljust(36), f'({get_corrupted_folders.__doc__})')
    print(f'        > unrecognized: {len(unrecognized)}'.ljust(36), f'({get_unrecognized_folders.__doc__})')
        
    print(SHELL_CONFIG.ANSI['reset'])

    if num_indexed:
        print('    {lightred}Hint:{reset} You can list link data directories by status like so:'.format(**SHELL_CONFIG.ANSI))
        print('        archivebox list --status=<status>  (e.g. indexed, corrupted, archived, etc.)')

    if orphaned:
        print('    {lightred}Hint:{reset} To automatically import orphaned data directories into the main index, run:'.format(**SHELL_CONFIG.ANSI))
        print('        archivebox init')

    if num_invalid:
        print('    {lightred}Hint:{reset} You may need to manually remove or fix some invalid data directories, afterwards make sure to run:'.format(**SHELL_CONFIG.ANSI))
        print('        archivebox init')
    
    print()
    print('{green}[*] Scanning recent archive changes and user logins:{reset}'.format(**SHELL_CONFIG.ANSI))
    print(SHELL_CONFIG.ANSI['lightyellow'], f'   {CONSTANTS.LOGS_DIR}/*', SHELL_CONFIG.ANSI['reset'])
    users = get_admins().values_list('username', flat=True)
    print(f'    UI users {len(users)}: {", ".join(users)}')
    last_login = User.objects.order_by('last_login').last()
    if last_login:
        print(f'    Last UI login: {last_login.username} @ {str(last_login.last_login)[:16]}')
    last_downloaded = Snapshot.objects.order_by('downloaded_at').last()
    if last_downloaded:
        print(f'    Last changes: {str(last_downloaded.downloaded_at)[:16]}')

    if not users:
        print()
        print('    {lightred}Hint:{reset} You can create an admin user by running:'.format(**SHELL_CONFIG.ANSI))
        print('        archivebox manage createsuperuser')

    print()
    for snapshot in links.order_by('-downloaded_at')[:10]:
        if not snapshot.downloaded_at:
            continue
        print(
            SHELL_CONFIG.ANSI['black'],
            (
                f'   > {str(snapshot.downloaded_at)[:16]} '
                f'[{snapshot.num_outputs} {("X", "√")[snapshot.is_archived]} {printable_filesize(snapshot.archive_size)}] '
                f'"{snapshot.title}": {snapshot.url}'
            )[:SHELL_CONFIG.TERM_WIDTH],
            SHELL_CONFIG.ANSI['reset'],
        )
    print(SHELL_CONFIG.ANSI['black'], '   ...', SHELL_CONFIG.ANSI['reset'])


@enforce_types
def oneshot(url: str, extractors: str="", out_dir: Path=DATA_DIR, created_by_id: int | None=None) -> List[Link]:
    """
    Create a single URL archive folder with an index.json and index.html, and all the archive method outputs.
    You can run this to archive single pages without needing to create a whole collection with archivebox init.
    """
    oneshot_link, _ = parse_links_memory([url])
    if len(oneshot_link) > 1:
        stderr(
                '[X] You should pass a single url to the oneshot command',
                color='red'
            )
        raise SystemExit(2)

    methods = extractors.split(",") if extractors else ignore_methods(['title'])
    archive_link(oneshot_link[0], out_dir=out_dir, methods=methods, created_by_id=created_by_id)
    return oneshot_link

@enforce_types
def add(urls: Union[str, List[str]],
        tag: str='',
        depth: int=0,
        update: bool=not ARCHIVING_CONFIG.ONLY_NEW,
        update_all: bool=False,
        index_only: bool=False,
        overwrite: bool=False,
        # duplicate: bool=False,  # TODO: reuse the logic from admin.py resnapshot to allow adding multiple snapshots by appending timestamp automatically
        init: bool=False,
        extractors: str="",
        parser: str="auto",
        created_by_id: int | None=None,
        out_dir: Path=DATA_DIR) -> List[Link]:
    """Add a new URL or list of URLs to your archive"""

    from core.models import Snapshot, Tag
    # from queues.supervisor_util import start_cli_workers, tail_worker_logs
    # from queues.tasks import bg_archive_link
    

    assert depth in (0, 1), 'Depth must be 0 or 1 (depth >1 is not supported yet)'

    extractors = extractors.split(",") if extractors else []

    if init:
        run_subcommand('init', stdin=None, pwd=out_dir)

    # Load list of links from the existing index
    check_data_folder()

    # worker = start_cli_workers()
    
    new_links: List[Link] = []
    all_links = load_main_index(out_dir=out_dir)

    log_importing_started(urls=urls, depth=depth, index_only=index_only)
    if isinstance(urls, str):
        # save verbatim stdin to sources
        write_ahead_log = save_text_as_source(urls, filename='{ts}-import.txt', out_dir=out_dir)
    elif isinstance(urls, list):
        # save verbatim args to sources
        write_ahead_log = save_text_as_source('\n'.join(urls), filename='{ts}-import.txt', out_dir=out_dir)
    

    new_links += parse_links_from_source(write_ahead_log, root_url=None, parser=parser)

    # If we're going one level deeper, download each link and look for more links
    new_links_depth = []
    if new_links and depth == 1:
        log_crawl_started(new_links)
        for new_link in new_links:
            try:
                downloaded_file = save_file_as_source(new_link.url, filename=f'{new_link.timestamp}-crawl-{new_link.domain}.txt', out_dir=out_dir)
                new_links_depth += parse_links_from_source(downloaded_file, root_url=new_link.url)
            except Exception as err:
                stderr('[!] Failed to get contents of URL {new_link.url}', err, color='red')

    imported_links = list({link.url: link for link in (new_links + new_links_depth)}.values())
    
    new_links = dedupe_links(all_links, imported_links)

    write_main_index(links=new_links, out_dir=out_dir, created_by_id=created_by_id)
    all_links = load_main_index(out_dir=out_dir)

    tags = [
        Tag.objects.get_or_create(name=name.strip(), defaults={'created_by_id': created_by_id})[0]
        for name in tag.split(',')
        if name.strip()
    ]
    if tags:
        for link in imported_links:
            snapshot = Snapshot.objects.get(url=link.url)
            snapshot.tags.add(*tags)
            snapshot.tags_str(nocache=True)
            snapshot.save()
        # print(f'    √ Tagged {len(imported_links)} Snapshots with {len(tags)} tags {tags_str}')

    if index_only:
        # mock archive all the links using the fake index_only extractor method in order to update their state
        if overwrite:
            archive_links(imported_links, overwrite=overwrite, methods=['index_only'], out_dir=out_dir, created_by_id=created_by_id)
        else:
            archive_links(new_links, overwrite=False, methods=['index_only'], out_dir=out_dir, created_by_id=created_by_id)
    else:
        # fully run the archive extractor methods for each link
        archive_kwargs = {
            "out_dir": out_dir,
            "created_by_id": created_by_id,
        }
        if extractors:
            archive_kwargs["methods"] = extractors

        stderr()

        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

        if update:
            stderr(f'[*] [{ts}] Archiving + updating {len(imported_links)}/{len(all_links)}', len(imported_links), 'URLs from added set...', color='green')
            archive_links(imported_links, overwrite=overwrite, **archive_kwargs)
        elif update_all:
            stderr(f'[*] [{ts}] Archiving + updating {len(all_links)}/{len(all_links)}', len(all_links), 'URLs from entire library...', color='green')
            archive_links(all_links, overwrite=overwrite, **archive_kwargs)
        elif overwrite:
            stderr(f'[*] [{ts}] Archiving + overwriting {len(imported_links)}/{len(all_links)}', len(imported_links), 'URLs from added set...', color='green')
            archive_links(imported_links, overwrite=True, **archive_kwargs)
        elif new_links:
            stderr(f'[*] [{ts}] Archiving {len(new_links)}/{len(all_links)} URLs from added set...', color='green')
            archive_links(new_links, overwrite=False, **archive_kwargs)

    # tail_worker_logs(worker['stdout_logfile'])

    # if CAN_UPGRADE:
    #     hint(f"There's a new version of ArchiveBox available! Your current version is {VERSION}. You can upgrade to {VERSIONS_AVAILABLE['recommended_version']['tag_name']} ({VERSIONS_AVAILABLE['recommended_version']['html_url']}). For more on how to upgrade: https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives\n")

    return new_links

@enforce_types
def remove(filter_str: Optional[str]=None,
           filter_patterns: Optional[List[str]]=None,
           filter_type: str='exact',
           snapshots: Optional[QuerySet]=None,
           after: Optional[float]=None,
           before: Optional[float]=None,
           yes: bool=False,
           delete: bool=False,
           out_dir: Path=DATA_DIR) -> List[Link]:
    """Remove the specified URLs from the archive"""
    
    check_data_folder()

    if snapshots is None:
        if filter_str and filter_patterns:
            stderr(
                '[X] You should pass either a pattern as an argument, '
                'or pass a list of patterns via stdin, but not both.\n',
                color='red',
            )
            raise SystemExit(2)
        elif not (filter_str or filter_patterns):
            stderr(
                '[X] You should pass either a pattern as an argument, '
                'or pass a list of patterns via stdin.',
                color='red',
            )
            stderr()
            hint(('To remove all urls you can run:',
                'archivebox remove --filter-type=regex ".*"'))
            stderr()
            raise SystemExit(2)
        elif filter_str:
            filter_patterns = [ptn.strip() for ptn in filter_str.split('\n')]

    list_kwargs = {
        "filter_patterns": filter_patterns,
        "filter_type": filter_type,
        "after": after,
        "before": before,
    }
    if snapshots:
        list_kwargs["snapshots"] = snapshots

    log_list_started(filter_patterns, filter_type)
    timer = TimedProgress(360, prefix='      ')
    try:
        snapshots = list_links(**list_kwargs)
    finally:
        timer.end()


    if not snapshots.exists():
        log_removal_finished(0, 0)
        raise SystemExit(1)


    log_links = [link.as_link() for link in snapshots]
    log_list_finished(log_links)
    log_removal_started(log_links, yes=yes, delete=delete)

    timer = TimedProgress(360, prefix='      ')
    try:
        for snapshot in snapshots:
            if delete:
                shutil.rmtree(snapshot.as_link().link_dir, ignore_errors=True)
    finally:
        timer.end()

    to_remove = snapshots.count()

    from .search import flush_search_index

    flush_search_index(snapshots=snapshots)
    remove_from_sql_main_index(snapshots=snapshots, out_dir=out_dir)
    all_snapshots = load_main_index(out_dir=out_dir)
    log_removal_finished(all_snapshots.count(), to_remove)
    
    return all_snapshots

@enforce_types
def update(resume: Optional[float]=None,
           only_new: bool=ARCHIVING_CONFIG.ONLY_NEW,
           index_only: bool=False,
           overwrite: bool=False,
           filter_patterns_str: Optional[str]=None,
           filter_patterns: Optional[List[str]]=None,
           filter_type: Optional[str]=None,
           status: Optional[str]=None,
           after: Optional[str]=None,
           before: Optional[str]=None,
           extractors: str="",
           out_dir: Path=DATA_DIR) -> List[Link]:
    """Import any new links from subscriptions and retry any previously failed/skipped links"""

    from core.models import ArchiveResult
    from .search import index_links
    # from .queues.supervisor_util import start_cli_workers
    

    check_data_folder()
    # start_cli_workers()
    new_links: List[Link] = [] # TODO: Remove input argument: only_new

    extractors = extractors.split(",") if extractors else []

    # Step 1: Filter for selected_links
    print('[*] Finding matching Snapshots to update...')
    print(f'    - Filtering by {" ".join(filter_patterns)} ({filter_type}) {before=} {after=} {status=}...')
    matching_snapshots = list_links(
        filter_patterns=filter_patterns,
        filter_type=filter_type,
        before=before,
        after=after,
    )
    print(f'    - Checking {matching_snapshots.count()} snapshot folders for existing data with {status=}...')
    matching_folders = list_folders(
        links=matching_snapshots,
        status=status,
        out_dir=out_dir,
    )
    all_links = (link for link in matching_folders.values() if link)
    print('    - Sorting by most unfinished -> least unfinished + date archived...')
    all_links = sorted(all_links, key=lambda link: (ArchiveResult.objects.filter(snapshot__url=link.url).count(), link.timestamp))

    if index_only:
        for link in all_links:
            write_link_details(link, out_dir=out_dir, skip_sql_index=True)
        index_links(all_links, out_dir=out_dir)
        return all_links
        
    # Step 2: Run the archive methods for each link
    to_archive = new_links if only_new else all_links
    if resume:
        to_archive = [
            link for link in to_archive
            if link.timestamp >= str(resume)
        ]
        if not to_archive:
            stderr('')
            stderr(f'[√] Nothing found to resume after {resume}', color='green')
            return all_links

    archive_kwargs = {
        "out_dir": out_dir,
    }
    if extractors:
        archive_kwargs["methods"] = extractors


    archive_links(to_archive, overwrite=overwrite, **archive_kwargs)

    # Step 4: Re-write links index with updated titles, icons, and resources
    all_links = load_main_index(out_dir=out_dir)
    return all_links

@enforce_types
def list_all(filter_patterns_str: Optional[str]=None,
             filter_patterns: Optional[List[str]]=None,
             filter_type: str='exact',
             status: Optional[str]=None,
             after: Optional[float]=None,
             before: Optional[float]=None,
             sort: Optional[str]=None,
             csv: Optional[str]=None,
             json: bool=False,
             html: bool=False,
             with_headers: bool=False,
             out_dir: Path=DATA_DIR) -> Iterable[Link]:
    """List, filter, and export information about archive entries"""
    
    check_data_folder()

    if filter_patterns and filter_patterns_str:
        stderr(
            '[X] You should either pass filter patterns as an arguments '
            'or via stdin, but not both.\n',
            color='red',
        )
        raise SystemExit(2)
    elif filter_patterns_str:
        filter_patterns = filter_patterns_str.split('\n')

    snapshots = list_links(
        filter_patterns=filter_patterns,
        filter_type=filter_type,
        before=before,
        after=after,
    )

    if sort:
        snapshots = snapshots.order_by(sort)

    folders = list_folders(
        links=snapshots,
        status=status,
        out_dir=out_dir,
    )

    if json: 
        output = generate_json_index_from_links(folders.values(), with_headers)
    elif html:
        output = generate_index_from_links(folders.values(), with_headers)
    elif csv:
        output = links_to_csv(folders.values(), cols=csv.split(','), header=with_headers)
    else:
        output = printable_folders(folders, with_headers=with_headers)
    print(output)
    return folders


@enforce_types
def list_links(snapshots: Optional[QuerySet]=None,
               filter_patterns: Optional[List[str]]=None,
               filter_type: str='exact',
               after: Optional[float]=None,
               before: Optional[float]=None,
               out_dir: Path=DATA_DIR) -> Iterable[Link]:
    
    check_data_folder()

    if snapshots:
        all_snapshots = snapshots
    else:
        all_snapshots = load_main_index(out_dir=out_dir)

    if after is not None:
        all_snapshots = all_snapshots.filter(timestamp__gte=after)
    if before is not None:
        all_snapshots = all_snapshots.filter(timestamp__lt=before)
    if filter_patterns:
        all_snapshots = snapshot_filter(all_snapshots, filter_patterns, filter_type)

    if not all_snapshots:
        stderr('[!] No Snapshots matched your filters:', filter_patterns, f'({filter_type})', color='lightyellow')

    return all_snapshots

@enforce_types
def list_folders(links: List[Link],
                 status: str,
                 out_dir: Path=DATA_DIR) -> Dict[str, Optional[Link]]:
    
    check_data_folder()

    STATUS_FUNCTIONS = {
        "indexed": get_indexed_folders,
        "archived": get_archived_folders,
        "unarchived": get_unarchived_folders,
        "present": get_present_folders,
        "valid": get_valid_folders,
        "invalid": get_invalid_folders,
        "duplicate": get_duplicate_folders,
        "orphaned": get_orphaned_folders,
        "corrupted": get_corrupted_folders,
        "unrecognized": get_unrecognized_folders,
    }

    try:
        return STATUS_FUNCTIONS[status](links, out_dir=out_dir)
    except KeyError:
        raise ValueError('Status not recognized.')

@enforce_types
def install(out_dir: Path=DATA_DIR) -> None:
    """Automatically install all ArchiveBox dependencies and extras"""
    
    # if running as root:
    #    - run init to create index + lib dir
    #    - chown -R 911 DATA_DIR
    #    - install all binaries as root
    #    - chown -R 911 LIB_DIR
    # else:
    #    - run init to create index + lib dir as current user
    #    - install all binaries as current user
    #    - recommend user re-run with sudo if any deps need to be installed as root

    from rich import print
    from django.conf import settings
    
    from archivebox import CONSTANTS
    from archivebox.config.permissions import IS_ROOT, ARCHIVEBOX_USER, ARCHIVEBOX_GROUP

    if not (os.access(ARCHIVE_DIR, os.R_OK) and ARCHIVE_DIR.is_dir()):
        run_subcommand('init', stdin=None, pwd=out_dir)  # must init full index because we need a db to store InstalledBinary entries in

    print('\n[green][+] Installing ArchiveBox dependencies automatically...[/green]')
    
    # we never want the data dir to be owned by root, detect owner of existing owner of DATA_DIR to try and guess desired non-root UID
    if IS_ROOT:
        EUID = os.geteuid()
        
        # if we have sudo/root permissions, take advantage of them just while installing dependencies
        print()
        print(f'[yellow]:warning:  Running as UID=[blue]{EUID}[/blue] with [red]sudo[/red] only for dependencies that need it.[/yellow]')
        print(f'    DATA_DIR, LIB_DIR, and TMP_DIR will be owned by [blue]{ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}[/blue].')
        print()
    
    
    package_manager_names = ', '.join(f'[yellow]{binprovider.name}[/yellow]' for binprovider in reversed(list(settings.BINPROVIDERS.values())))
    print(f'[+] Setting up package managers {package_manager_names}...')
    for binprovider in reversed(list(settings.BINPROVIDERS.values())):
        try:
            binprovider.setup()
        except Exception:
            # it's ok, installing binaries below will automatically set up package managers as needed
            # e.g. if user does not have npm available we cannot set it up here yet, but once npm Binary is installed
            # the next package that depends on npm will automatically call binprovider.setup() during its own install
            pass
    
    print()
    
    for binary in reversed(list(settings.BINARIES.values())):
        providers = ' [grey53]or[/grey53] '.join(provider.name for provider in binary.binproviders_supported)
        print(f'[+] Detecting / Installing [yellow]{binary.name.ljust(22)}[/yellow] using [red]{providers}[/red]...')
        try:
            with SudoPermission(uid=0, fallback=True):
                # print(binary.load_or_install(fresh=True).model_dump(exclude={'provider_overrides', 'bin_dir', 'hook_type'}))
                binary.load_or_install(fresh=True).model_dump(exclude={'provider_overrides', 'bin_dir', 'hook_type'})
            if IS_ROOT:
                with SudoPermission(uid=0):
                    if ARCHIVEBOX_USER == 0:
                        os.system(f'chmod -R 777 "{CONSTANTS.LIB_DIR.resolve()}"')
                    else:    
                        os.system(f'chown -R {ARCHIVEBOX_USER} "{CONSTANTS.LIB_DIR.resolve()}"')
        except Exception as e:
            print(f'[red]:cross_mark: Failed to install {binary.name} as user {ARCHIVEBOX_USER}: {e}[/red]')
                

    from django.contrib.auth import get_user_model
    User = get_user_model()

    if not User.objects.filter(is_superuser=True).exists():
        stderr('\n[+] Don\'t forget to create a new admin user for the Web UI...', color='green')
        stderr('    archivebox manage createsuperuser')
        # run_subcommand('manage', subcommand_args=['createsuperuser'], pwd=out_dir)
    
    print('\n[green][√] Set up ArchiveBox and its dependencies successfully.[/green]\n', file=sys.stderr)
    
    from plugins_pkg.pip.apps import ARCHIVEBOX_BINARY
    
    proc = run_shell([ARCHIVEBOX_BINARY.load().abspath, 'version'], capture_output=False, cwd=out_dir)
    raise SystemExit(proc.returncode)


# backwards-compatibility:
setup = install


@enforce_types
def config(config_options_str: Optional[str]=None,
           config_options: Optional[List[str]]=None,
           get: bool=False,
           set: bool=False,
           reset: bool=False,
           out_dir: Path=DATA_DIR) -> None:
    """Get and set your ArchiveBox project configuration values"""

    from rich import print

    check_data_folder()
    if config_options and config_options_str:
        stderr(
            '[X] You should either pass config values as an arguments '
            'or via stdin, but not both.\n',
            color='red',
        )
        raise SystemExit(2)
    elif config_options_str:
        config_options = config_options_str.split('\n')

    from django.conf import settings
    
    config_options = config_options or []

    no_args = not (get or set or reset or config_options)

    matching_config = {}
    if get or no_args:
        if config_options:
            config_options = [get_real_name(key) for key in config_options]
            matching_config = {key: settings.FLAT_CONFIG[key] for key in config_options if key in settings.FLAT_CONFIG}
            failed_config = [key for key in config_options if key not in settings.FLAT_CONFIG]
            if failed_config:
                stderr()
                stderr('[X] These options failed to get', color='red')
                stderr('    {}'.format('\n    '.join(config_options)))
                raise SystemExit(1)
        else:
            matching_config = settings.FLAT_CONFIG
        
        print(printable_config(matching_config))
        raise SystemExit(not matching_config)
    elif set:
        new_config = {}
        failed_options = []
        for line in config_options:
            if line.startswith('#') or not line.strip():
                continue
            if '=' not in line:
                stderr('[X] Config KEY=VALUE must have an = sign in it', color='red')
                stderr(f'    {line}')
                raise SystemExit(2)

            raw_key, val = line.split('=', 1)
            raw_key = raw_key.upper().strip()
            key = get_real_name(raw_key)
            if key != raw_key:
                stderr(f'[i] Note: The config option {raw_key} has been renamed to {key}, please use the new name going forwards.', color='lightyellow')

            if key in settings.FLAT_CONFIG:
                new_config[key] = val.strip()
            else:
                failed_options.append(line)

        if new_config:
            before = settings.FLAT_CONFIG
            matching_config = write_config_file(new_config, out_dir=DATA_DIR)
            after = load_all_config()
            print(printable_config(matching_config))

            side_effect_changes = {}
            for key, val in after.items():
                if key in settings.FLAT_CONFIG and (before[key] != after[key]) and (key not in matching_config):
                    side_effect_changes[key] = after[key]

            if side_effect_changes:
                stderr()
                stderr('[i] Note: This change also affected these other options that depended on it:', color='lightyellow')
                print('    {}'.format(printable_config(side_effect_changes, prefix='    ')))
        if failed_options:
            stderr()
            stderr('[X] These options failed to set (check for typos):', color='red')
            stderr('    {}'.format('\n    '.join(failed_options)))
            raise SystemExit(1)
    elif reset:
        stderr('[X] This command is not implemented yet.', color='red')
        stderr('    Please manually remove the relevant lines from your config file:')
        raise SystemExit(2)
    else:
        stderr('[X] You must pass either --get or --set, or no arguments to get the whole config.', color='red')
        stderr('    archivebox config')
        stderr('    archivebox config --get SOME_KEY')
        stderr('    archivebox config --set SOME_KEY=SOME_VALUE')
        raise SystemExit(2)


@enforce_types
def schedule(add: bool=False,
             show: bool=False,
             clear: bool=False,
             foreground: bool=False,
             run_all: bool=False,
             quiet: bool=False,
             every: Optional[str]=None,
             tag: str='',
             depth: int=0,
             overwrite: bool=False,
             update: bool=not ARCHIVING_CONFIG.ONLY_NEW,
             import_path: Optional[str]=None,
             out_dir: Path=DATA_DIR):
    """Set ArchiveBox to regularly import URLs at specific times using cron"""
    
    check_data_folder()
    from archivebox.plugins_pkg.pip.apps import ARCHIVEBOX_BINARY
    from archivebox.config.permissions import USER

    Path(CONSTANTS.LOGS_DIR).mkdir(exist_ok=True)

    cron = CronTab(user=True)
    cron = dedupe_cron_jobs(cron)

    if clear:
        print(cron.remove_all(comment=CRON_COMMENT))
        cron.write()
        raise SystemExit(0)

    existing_jobs = list(cron.find_comment(CRON_COMMENT))

    if every or add:
        every = every or 'day'
        quoted = lambda s: f'"{s}"' if (s and ' ' in str(s)) else str(s)
        cmd = [
            'cd',
            quoted(out_dir),
            '&&',
            quoted(ARCHIVEBOX_BINARY.load().abspath),
            *([
                'add',
                *(['--overwrite'] if overwrite else []),
                *(['--update'] if update else []),
                *([f'--tag={tag}'] if tag else []),
                f'--depth={depth}',
                f'"{import_path}"',
            ] if import_path else ['update']),
            '>>',
            quoted(Path(CONSTANTS.LOGS_DIR) / 'schedule.log'),
            '2>&1',

        ]
        new_job = cron.new(command=' '.join(cmd), comment=CRON_COMMENT)

        if every in ('minute', 'hour', 'day', 'month', 'year'):
            set_every = getattr(new_job.every(), every)
            set_every()
        elif CronSlices.is_valid(every):
            new_job.setall(every)
        else:
            stderr('{red}[X] Got invalid timeperiod for cron task.{reset}'.format(**SHELL_CONFIG.ANSI))
            stderr('    It must be one of minute/hour/day/month')
            stderr('    or a quoted cron-format schedule like:')
            stderr('        archivebox init --every=day --depth=1 https://example.com/some/rss/feed.xml')
            stderr('        archivebox init --every="0/5 * * * *" --depth=1 https://example.com/some/rss/feed.xml')
            raise SystemExit(1)

        cron = dedupe_cron_jobs(cron)
        cron.write()

        total_runs = sum(j.frequency_per_year() for j in cron)
        existing_jobs = list(cron.find_comment(CRON_COMMENT))

        print()
        print('{green}[√] Scheduled new ArchiveBox cron job for user: {} ({} jobs are active).{reset}'.format(USER, len(existing_jobs), **SHELL_CONFIG.ANSI))
        print('\n'.join(f'  > {cmd}' if str(cmd) == str(new_job) else f'    {cmd}' for cmd in existing_jobs))
        if total_runs > 60 and not quiet:
            stderr()
            stderr('{lightyellow}[!] With the current cron config, ArchiveBox is estimated to run >{} times per year.{reset}'.format(total_runs, **SHELL_CONFIG.ANSI))
            stderr('    Congrats on being an enthusiastic internet archiver! 👌')
            stderr()
            stderr('    Make sure you have enough storage space available to hold all the data.')
            stderr('    Using a compressed/deduped filesystem like ZFS is recommended if you plan on archiving a lot.')
            stderr('')
    elif show:
        if existing_jobs:
            print('\n'.join(str(cmd) for cmd in existing_jobs))
        else:
            stderr('{red}[X] There are no ArchiveBox cron jobs scheduled for your user ({}).{reset}'.format(USER, **SHELL_CONFIG.ANSI))
            stderr('    To schedule a new job, run:')
            stderr('        archivebox schedule --every=[timeperiod] --depth=1 https://example.com/some/rss/feed.xml')
        raise SystemExit(0)

    cron = CronTab(user=True)
    cron = dedupe_cron_jobs(cron)
    existing_jobs = list(cron.find_comment(CRON_COMMENT))

    if foreground or run_all:
        if not existing_jobs:
            stderr('{red}[X] You must schedule some jobs first before running in foreground mode.{reset}'.format(**SHELL_CONFIG.ANSI))
            stderr('    archivebox schedule --every=hour --depth=1 https://example.com/some/rss/feed.xml')
            raise SystemExit(1)

        print('{green}[*] Running {} ArchiveBox jobs in foreground task scheduler...{reset}'.format(len(existing_jobs), **SHELL_CONFIG.ANSI))
        if run_all:
            try:
                for job in existing_jobs:
                    sys.stdout.write(f'  > {job.command.split("/archivebox ")[0].split(" && ")[0]}\n')
                    sys.stdout.write(f'    > {job.command.split("/archivebox ")[-1].split(" >> ")[0]}')
                    sys.stdout.flush()
                    job.run()
                    sys.stdout.write(f'\r    √ {job.command.split("/archivebox ")[-1]}\n')
            except KeyboardInterrupt:
                print('\n{green}[√] Stopped.{reset}'.format(**SHELL_CONFIG.ANSI))
                raise SystemExit(1)

        if foreground:
            try:
                for job in existing_jobs:
                    print(f'  > {job.command.split("/archivebox ")[-1].split(" >> ")[0]}')
                for result in cron.run_scheduler():
                    print(result)
            except KeyboardInterrupt:
                print('\n{green}[√] Stopped.{reset}'.format(**SHELL_CONFIG.ANSI))
                raise SystemExit(1)

    # if CAN_UPGRADE:
    #     hint(f"There's a new version of ArchiveBox available! Your current version is {VERSION}. You can upgrade to {VERSIONS_AVAILABLE['recommended_version']['tag_name']} ({VERSIONS_AVAILABLE['recommended_version']['html_url']}). For more on how to upgrade: https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives\n")

    
@enforce_types
def server(runserver_args: Optional[List[str]]=None,
           reload: bool=False,
           debug: bool=False,
           init: bool=False,
           quick_init: bool=False,
           createsuperuser: bool=False,
           daemonize: bool=False,
           out_dir: Path=DATA_DIR) -> None:
    """Run the ArchiveBox HTTP server"""

    from rich import print

    runserver_args = runserver_args or []
    
    if init:
        run_subcommand('init', stdin=None, pwd=out_dir)
        print()
    elif quick_init:
        run_subcommand('init', subcommand_args=['--quick'], stdin=None, pwd=out_dir)
        print()

    if createsuperuser:
        run_subcommand('manage', subcommand_args=['createsuperuser'], pwd=out_dir)
        print()


    check_data_folder()

    from django.core.management import call_command
    from django.contrib.auth.models import User
    
    

    print('[green][+] Starting ArchiveBox webserver...[/green]')
    print('    > Logging errors to ./logs/errors.log')
    if not User.objects.filter(is_superuser=True).exists():
        print('[yellow][!] No admin users exist yet, you will not be able to edit links in the UI.[/yellow]')
        print()
        print('    [violet]Hint:[/violet] To create an admin user, run:')
        print('        archivebox manage createsuperuser')
        print()
    

    if SHELL_CONFIG.DEBUG:
        if not reload:
            runserver_args.append('--noreload')  # '--insecure'
        call_command("runserver", *runserver_args)
    else:
        host = '127.0.0.1'
        port = '8000'
        
        try:
            host_and_port = [arg for arg in runserver_args if arg.replace('.', '').replace(':', '').isdigit()][0]
            if ':' in host_and_port:
                host, port = host_and_port.split(':')
            else:
                if '.' in host_and_port:
                    host = host_and_port
                else:
                    port = host_and_port
        except IndexError:
            pass

        print(f'    [blink][green]>[/green][/blink] Starting ArchiveBox webserver on [deep_sky_blue4][link=http://{host}:{port}]http://{host}:{port}[/link][/deep_sky_blue4]')

        from queues.supervisor_util import start_server_workers

        print()
        
        start_server_workers(host=host, port=port, daemonize=False)

        print("\n[i][green][🟩] ArchiveBox server shut down gracefully.[/green][/i]")


@enforce_types
def manage(args: Optional[List[str]]=None, out_dir: Path=DATA_DIR) -> None:
    """Run an ArchiveBox Django management command"""

    check_data_folder()
    from django.core.management import execute_from_command_line

    if (args and "createsuperuser" in args) and (IN_DOCKER and not SHELL_CONFIG.IS_TTY):
        stderr('[!] Warning: you need to pass -it to use interactive commands in docker', color='lightyellow')
        stderr('    docker run -it archivebox manage {}'.format(' '.join(args or ['...'])), color='lightyellow')
        stderr('')
        
    # import ipdb; ipdb.set_trace()

    execute_from_command_line(['manage.py', *(args or ['help'])])


@enforce_types
def shell(out_dir: Path=DATA_DIR) -> None:
    """Enter an interactive ArchiveBox Django shell"""

    check_data_folder()

    from django.core.management import call_command
    call_command("shell_plus")

