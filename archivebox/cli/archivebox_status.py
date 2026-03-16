#!/usr/bin/env python3

__package__ = 'archivebox.cli'

from pathlib import Path

import rich_click as click
from rich import print

from archivebox.misc.util import enforce_types, docstring
from archivebox.config import DATA_DIR, CONSTANTS, ARCHIVE_DIR
from archivebox.config.common import SHELL_CONFIG
from archivebox.misc.legacy import parse_json_links_details
from archivebox.misc.system import get_dir_size
from archivebox.misc.logging_util import printable_filesize


@enforce_types
def status(out_dir: Path=DATA_DIR) -> None:
    """Print out some info and statistics about the archive collection"""

    from django.contrib.auth import get_user_model
    from archivebox.core.models import Snapshot
    User = get_user_model()

    print('[green]\\[*] Scanning archive main index...[/green]')
    print(f'[yellow]   {out_dir}/*[/yellow]')
    num_bytes, num_dirs, num_files = get_dir_size(out_dir, recursive=False, pattern='index.')
    size = printable_filesize(num_bytes)
    print(f'    Index size: {size} across {num_files} files')
    print()

    links = list(Snapshot.objects.all())
    num_sql_links = len(links)
    num_link_details = sum(1 for link in parse_json_links_details(out_dir=out_dir))
    print(f'    > SQL Main Index: {num_sql_links} links'.ljust(36), f'(found in {CONSTANTS.SQL_INDEX_FILENAME})')
    print(f'    > JSON Link Details: {num_link_details} links'.ljust(36), f'(found in {ARCHIVE_DIR.name}/*/index.json)')
    print()
    print('[green]\\[*] Scanning archive data directories...[/green]')
    users_dir = out_dir / 'users'
    scan_roots = [root for root in (ARCHIVE_DIR, users_dir) if root.exists()]
    scan_roots_display = ', '.join(str(root) for root in scan_roots) if scan_roots else str(ARCHIVE_DIR)
    print(f'[yellow]   {scan_roots_display}[/yellow]')
    num_bytes = num_dirs = num_files = 0
    for root in scan_roots:
        root_bytes, root_dirs, root_files = get_dir_size(root)
        num_bytes += root_bytes
        num_dirs += root_dirs
        num_files += root_files
    size = printable_filesize(num_bytes)
    print(f'    Size: {size} across {num_files} files in {num_dirs} directories')

    # Use DB as source of truth for snapshot status
    num_indexed = len(links)
    num_archived = sum(1 for snapshot in links if snapshot.is_archived)
    num_unarchived = max(num_indexed - num_archived, 0)
    print(f'    > indexed: {num_indexed}'.ljust(36), '(total snapshots in DB)')
    print(f'      > archived: {num_archived}'.ljust(36), '(snapshots with archived content)')
    print(f'      > unarchived: {num_unarchived}'.ljust(36), '(snapshots pending archiving)')

    # Count snapshot directories on filesystem across both legacy and current layouts.
    expected_snapshot_dirs = {
        str(Path(snapshot.output_dir).resolve())
        for snapshot in links
        if Path(snapshot.output_dir).exists()
    }
    discovered_snapshot_dirs = set()

    if ARCHIVE_DIR.exists():
        discovered_snapshot_dirs.update(
            str(entry.resolve())
            for entry in ARCHIVE_DIR.iterdir()
            if entry.is_dir()
        )

    if users_dir.exists():
        discovered_snapshot_dirs.update(
            str(entry.resolve())
            for entry in users_dir.glob('*/snapshots/*/*/*')
            if entry.is_dir()
        )

    orphaned_dirs = sorted(discovered_snapshot_dirs - expected_snapshot_dirs)
    num_present = len(discovered_snapshot_dirs)
    num_valid = len(discovered_snapshot_dirs & expected_snapshot_dirs)
    print()
    print(f'    > present: {num_present}'.ljust(36), '(snapshot directories on disk)')
    print(f'      > [green]valid:[/green] {num_valid}'.ljust(36), '               (directories with matching DB entry)')

    num_orphaned = len(orphaned_dirs)
    print(f'      > [red]orphaned:[/red] {num_orphaned}'.ljust(36), '         (directories without matching DB entry)')

    if num_indexed:
        print('    [violet]Hint:[/violet] You can list snapshots by status like so:')
        print('        [green]archivebox list --status=<status>  (e.g. archived, queued, etc.)[/green]')

    if orphaned_dirs:
        print('    [violet]Hint:[/violet] To automatically import orphaned data directories into the main index, run:')
        print('        [green]archivebox init[/green]')

    print()
    print('[green]\\[*] Scanning recent archive changes and user logins:[/green]')
    print(f'[yellow]   {CONSTANTS.LOGS_DIR}/*[/yellow]')
    admin_users = User.objects.filter(is_superuser=True).exclude(username='system')
    users = [user.get_username() for user in admin_users]
    print(f'    UI users {len(users)}: {", ".join(users)}')
    last_login = admin_users.order_by('last_login').last()
    if last_login:
        print(f'    Last UI login: {last_login.get_username()} @ {str(last_login.last_login)[:16]}')
    last_downloaded = Snapshot.objects.order_by('downloaded_at').last()
    if last_downloaded:
        print(f'    Last changes: {str(last_downloaded.downloaded_at)[:16]}')

    if not users:
        print()
        print('    [violet]Hint:[/violet] You can create an admin user by running:')
        print('        [green]archivebox manage createsuperuser[/green]')

    print()
    recent_snapshots = sorted(
        links,
        key=lambda snapshot: (
            snapshot.downloaded_at or snapshot.modified_at or snapshot.created_at
        ),
        reverse=True,
    )[:10]
    for snapshot in recent_snapshots:
        if not snapshot.downloaded_at:
            continue
        print(
            (
                '[grey53] '
                f'   > {str(snapshot.downloaded_at)[:16]} '
                f'[{snapshot.num_outputs} {("X", "√")[snapshot.is_archived]} {printable_filesize(snapshot.archive_size)}] '
                f'"{snapshot.title}": {snapshot.url}'
                '[/grey53]'
            )[:SHELL_CONFIG.TERM_WIDTH],
        )
    print('[grey53]   ...')


@click.command()
@docstring(status.__doc__)
def main(**kwargs):
    """Print out some info and statistics about the archive collection"""
    status(**kwargs)


if __name__ == '__main__':
    main()
