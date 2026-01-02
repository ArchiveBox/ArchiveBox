#!/usr/bin/env python3

__package__ = 'archivebox.cli'

import os
import sys
from pathlib import Path

from rich import print
import rich_click as click

from archivebox.misc.util import docstring, enforce_types


@enforce_types
def init(force: bool=False, quick: bool=False, install: bool=False) -> None:
    """Initialize a new ArchiveBox collection in the current directory"""
    
    from archivebox.config import CONSTANTS, VERSION, DATA_DIR
    from archivebox.config.common import SERVER_CONFIG
    from archivebox.config.collection import write_config_file
    from archivebox.misc.legacy import parse_json_main_index, parse_json_links_details, SnapshotDict
    from archivebox.misc.db import apply_migrations
    
    # if os.access(out_dir / CONSTANTS.JSON_INDEX_FILENAME, os.F_OK):
    #     print("[red]:warning: This folder contains a JSON index. It is deprecated, and will no longer be kept up to date automatically.[/red]", file=sys.stderr)
    #     print("[red]    You can run `archivebox list --json --with-headers > static_index.json` to manually generate it.[/red]", file=sys.stderr)

    is_empty = not len(set(os.listdir(DATA_DIR)) - CONSTANTS.ALLOWED_IN_DATA_DIR)
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
    _get_collection_id(DATA_DIR, force_create=True)
    
    # create the ArchiveBox.conf file
    write_config_file({'SECRET_KEY': SERVER_CONFIG.SECRET_KEY})


    if os.access(CONSTANTS.DATABASE_FILE, os.F_OK):
        print('\n[green][*] Verifying main SQL index and running any migrations needed...[/green]')
    else:
        print('\n[green][+] Building main SQL index and running initial migrations...[/green]')
    
    from archivebox.config.django import setup_django
    setup_django()
    
    for migration_line in apply_migrations(DATA_DIR):
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

    from archivebox.core.models import Snapshot

    all_links = Snapshot.objects.none()
    pending_links: dict[str, SnapshotDict] = {}

    if existing_index:
        all_links = Snapshot.objects.all()
        print(f'    √ Loaded {all_links.count()} links from existing main index.')

    if quick:
        print('    > Skipping orphan snapshot import (quick mode)')
    else:
        try:
            # Import orphaned links from legacy JSON indexes
            orphaned_json_links = {
                link_dict['url']: link_dict
                for link_dict in parse_json_main_index(DATA_DIR)
                if not all_links.filter(url=link_dict['url']).exists()
            }
            if orphaned_json_links:
                pending_links.update(orphaned_json_links)
                print(f'    [yellow]√ Added {len(orphaned_json_links)} orphaned links from existing JSON index...[/yellow]')

            orphaned_data_dir_links = {
                link_dict['url']: link_dict
                for link_dict in parse_json_links_details(DATA_DIR)
                if not all_links.filter(url=link_dict['url']).exists()
            }
            if orphaned_data_dir_links:
                pending_links.update(orphaned_data_dir_links)
                print(f'    [yellow]√ Added {len(orphaned_data_dir_links)} orphaned links from existing archive directories.[/yellow]')

            if pending_links:
                for link_dict in pending_links.values():
                    Snapshot.from_json(link_dict)

            # Hint for orphaned snapshot directories
            print()
            print('    [violet]Hint:[/violet] To import orphaned snapshot directories and reconcile filesystem state, run:')
            print('        archivebox update')

        except (KeyboardInterrupt, SystemExit):
            print(file=sys.stderr)
            print('[yellow]:stop_sign: Stopped checking archive directories due to Ctrl-C/SIGTERM[/yellow]', file=sys.stderr)
            print('    Your archive data is safe, but you should re-run `archivebox init` to finish the process later.', file=sys.stderr)
            print(file=sys.stderr)
            print('    [violet]Hint:[/violet] In the future you can run a quick init without checking dirs like so:', file=sys.stderr)
            print('        archivebox init --quick', file=sys.stderr)
            raise SystemExit(1)

    print('\n[green]----------------------------------------------------------------------[/green]')

    from django.contrib.auth.models import User

    if (SERVER_CONFIG.ADMIN_USERNAME and SERVER_CONFIG.ADMIN_PASSWORD) and not User.objects.filter(username=SERVER_CONFIG.ADMIN_USERNAME).exists():
        print('[green][+] Found ADMIN_USERNAME and ADMIN_PASSWORD configuration options, creating new admin user.[/green]')
        User.objects.create_superuser(username=SERVER_CONFIG.ADMIN_USERNAME, password=SERVER_CONFIG.ADMIN_PASSWORD)

    if existing_index:
        print('[green][√] Done. Verified and updated the existing ArchiveBox collection.[/green]')
    else:
        print(f'[green][√] Done. A new ArchiveBox collection was initialized ({len(all_links) + len(pending_links)} links).[/green]')

    
    CONSTANTS.PERSONAS_DIR.mkdir(parents=True, exist_ok=True)
    CONSTANTS.DEFAULT_TMP_DIR.mkdir(parents=True, exist_ok=True)
    CONSTANTS.DEFAULT_LIB_DIR.mkdir(parents=True, exist_ok=True)
    (CONSTANTS.DEFAULT_LIB_DIR / 'bin').mkdir(parents=True, exist_ok=True)

    from archivebox.config.common import STORAGE_CONFIG
    STORAGE_CONFIG.TMP_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_CONFIG.LIB_DIR.mkdir(parents=True, exist_ok=True)
    (STORAGE_CONFIG.LIB_DIR / 'bin').mkdir(parents=True, exist_ok=True)
    
    if install:
        from archivebox.cli.archivebox_install import install as install_method
        install_method()

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



@click.command()
@click.option('--force', '-f', is_flag=True, help='Ignore unrecognized files in current directory and initialize anyway')
@click.option('--quick', '-q', is_flag=True, help='Run any updates or migrations without rechecking all snapshot dirs')
@click.option('--install', '-s', is_flag=True, help='Automatically install dependencies and extras used for archiving')
@docstring(init.__doc__)
def main(**kwargs) -> None:
    init(**kwargs)


if __name__ == '__main__':
    main()
