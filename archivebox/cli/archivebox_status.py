#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox status'

import sys
import argparse
from pathlib import Path
from typing import Optional, List, IO

from rich import print

from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR
from archivebox.misc.logging_util import SmartFormatter, reject_stdin




# @enforce_types
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



@docstring(status.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=status.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    parser.parse_args(args or ())
    reject_stdin(__command__, stdin)

    status(out_dir=Path(pwd) if pwd else DATA_DIR)


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
