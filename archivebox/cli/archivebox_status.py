#!/usr/bin/env python3

__package__ = 'archivebox.cli'

from pathlib import Path

import rich_click as click
from rich import print

from archivebox.misc.util import enforce_types, docstring
from archivebox.config import DATA_DIR, CONSTANTS, ARCHIVE_DIR
from archivebox.config.common import SHELL_CONFIG
from archivebox.index.json import parse_json_links_details
from archivebox.index import (
    load_main_index,
    get_indexed_folders,
    get_archived_folders,
    get_invalid_folders,
    get_unarchived_folders,
    get_present_folders,
    get_valid_folders,
    get_duplicate_folders,
    get_orphaned_folders,
    get_corrupted_folders,
    get_unrecognized_folders,
)
from archivebox.misc.system import get_dir_size
from archivebox.misc.logging_util import printable_filesize


@enforce_types
def status(out_dir: Path=DATA_DIR) -> None:
    """Print out some info and statistics about the archive collection"""

    from django.contrib.auth import get_user_model
    from archivebox.index.sql import get_admins
    from core.models import Snapshot
    User = get_user_model()

    print('[green]\\[*] Scanning archive main index...[/green]')
    print(f'[yellow]   {out_dir}/*[/yellow]')
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
    print('[green]\\[*] Scanning archive data directories...[/green]')
    print(f'[yellow]   {ARCHIVE_DIR}/*[/yellow]')
    num_bytes, num_dirs, num_files = get_dir_size(ARCHIVE_DIR)
    size = printable_filesize(num_bytes)
    print(f'    Size: {size} across {num_files} files in {num_dirs} directories')

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
    print(f'      > [green]valid:[/green] {num_valid}'.ljust(36), f'               ({get_valid_folders.__doc__})')
    
    duplicate = get_duplicate_folders(links, out_dir=out_dir)
    orphaned = get_orphaned_folders(links, out_dir=out_dir)
    corrupted = get_corrupted_folders(links, out_dir=out_dir)
    unrecognized = get_unrecognized_folders(links, out_dir=out_dir)
    num_invalid = len({**duplicate, **orphaned, **corrupted, **unrecognized})
    print(f'      > [red]invalid:[/red] {num_invalid}'.ljust(36), f'           ({get_invalid_folders.__doc__})')
    print(f'        > duplicate: {len(duplicate)}'.ljust(36), f'({get_duplicate_folders.__doc__})')
    print(f'        > orphaned: {len(orphaned)}'.ljust(36), f'({get_orphaned_folders.__doc__})')
    print(f'        > corrupted: {len(corrupted)}'.ljust(36), f'({get_corrupted_folders.__doc__})')
    print(f'        > unrecognized: {len(unrecognized)}'.ljust(36), f'({get_unrecognized_folders.__doc__})')

    if num_indexed:
        print('    [violet]Hint:[/violet] You can list link data directories by status like so:')
        print('        [green]archivebox list --status=<status>  (e.g. indexed, corrupted, archived, etc.)[/green]')

    if orphaned:
        print('    [violet]Hint:[/violet] To automatically import orphaned data directories into the main index, run:')
        print('        [green]archivebox init[/green]')

    if num_invalid:
        print('    [violet]Hint:[/violet] You may need to manually remove or fix some invalid data directories, afterwards make sure to run:')
        print('        [green]archivebox init[/green]')
    
    print()
    print('[green]\\[*] Scanning recent archive changes and user logins:[/green]')
    print(f'[yellow]   {CONSTANTS.LOGS_DIR}/*[/yellow]')
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
        print('    [violet]Hint:[/violet] You can create an admin user by running:')
        print('        [green]archivebox manage createsuperuser[/green]')

    print()
    for snapshot in links.order_by('-downloaded_at')[:10]:
        if not snapshot.downloaded_at:
            continue
        print(
            '[grey53] ' +
            (
                f'   > {str(snapshot.downloaded_at)[:16]} '
                f'[{snapshot.num_outputs} {("X", "√")[snapshot.is_archived]} {printable_filesize(snapshot.archive_size)}] '
                f'"{snapshot.title}": {snapshot.url}'
            )[:SHELL_CONFIG.TERM_WIDTH]
            + '[grey53]',
        )
    print('[grey53]   ...')


@click.command()
@docstring(status.__doc__)
def main(**kwargs):
    """Print out some info and statistics about the archive collection"""
    status(**kwargs)


if __name__ == '__main__':
    main()
