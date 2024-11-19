#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox init'

import sys
import argparse
from pathlib import Path
from typing import Optional, List, IO


from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR
from archivebox.misc.logging_util import SmartFormatter, reject_stdin


def init(force: bool=False, quick: bool=False, install: bool=False, out_dir: Path=DATA_DIR) -> None:
    """Initialize a new ArchiveBox collection in the current directory"""
    
    from core.models import Snapshot
    from rich import print
    
    # if os.access(out_dir / CONSTANTS.JSON_INDEX_FILENAME, os.F_OK):
    #     print("[red]:warning: This folder contains a JSON index. It is deprecated, and will no longer be kept up to date automatically.[/red]", file=sys.stderr)
    #     print("[red]    You can run `archivebox list --json --with-headers > static_index.json` to manually generate it.[/red]", file=sys.stderr)

    is_empty = not len(set(os.listdir(out_dir)) - CONSTANTS.ALLOWED_IN_DATA_DIR)
    existing_index = os.path.isfile(CONSTANTS.DATABASE_FILE)
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
    
    # create the .archivebox_id file with a unique ID for this collection
    from archivebox.config.paths import _get_collection_id
    _get_collection_id(CONSTANTS.DATA_DIR, force_create=True)
    
    # create the ArchiveBox.conf file
    write_config_file({'SECRET_KEY': SERVER_CONFIG.SECRET_KEY})


    if os.access(CONSTANTS.DATABASE_FILE, os.F_OK):
        print('\n[green][*] Verifying main SQL index and running any migrations needed...[/green]')
    else:
        print('\n[green][+] Building main SQL index and running initial migrations...[/green]')
    
    for migration_line in apply_migrations(out_dir):
        sys.stdout.write(f'    {migration_line}\n')

    assert os.path.isfile(CONSTANTS.DATABASE_FILE) and os.access(CONSTANTS.DATABASE_FILE, os.R_OK)
    print()
    print(f'    √ ./{CONSTANTS.DATABASE_FILE.relative_to(DATA_DIR)}')
    
    # from django.contrib.auth.models import User
    # if SHELL_CONFIG.IS_TTY and not User.objects.filter(is_superuser=True).exclude(username='system').exists():
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
    CONSTANTS.DEFAULT_TMP_DIR.mkdir(parents=True, exist_ok=True)
    CONSTANTS.DEFAULT_LIB_DIR.mkdir(parents=True, exist_ok=True)
    
    from archivebox.config.common import STORAGE_CONFIG
    STORAGE_CONFIG.TMP_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_CONFIG.LIB_DIR.mkdir(parents=True, exist_ok=True)
    
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


@docstring(init.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=init.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    parser.add_argument(
        '--force', # '-f',
        action='store_true',
        help='Ignore unrecognized files in current directory and initialize anyway',
    )
    parser.add_argument(
        '--quick', '-q',
        action='store_true',
        help='Run any updates or migrations without rechecking all snapshot dirs',
    )
    parser.add_argument(
        '--install', #'-s',
        action='store_true',
        help='Automatically install dependencies and extras used for archiving',
    )
    parser.add_argument(
        '--setup', #'-s',
        action='store_true',
        help='DEPRECATED: equivalent to --install',
    )
    command = parser.parse_args(args or ())
    reject_stdin(__command__, stdin)

    init(
        force=command.force,
        quick=command.quick,
        install=command.install or command.setup,
        out_dir=pwd or DATA_DIR,
    )
    

if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
