#!/usr/bin/env python3

__package__ = "archivebox.cli"

from pathlib import Path

import rich_click as click
from rich import print

from archivebox.misc.util import enforce_types, docstring
from archivebox.config import CONSTANTS
from archivebox.config.common import get_config
from archivebox.misc.system import get_dir_size
from archivebox.misc.logging_util import printable_filesize


MAX_STATUS_FS_DIR_SCAN = 5000


@enforce_types
def status(out_dir: Path = CONSTANTS.DATA_DIR) -> None:
    """Print out some info and statistics about the archive collection"""

    from django.contrib.auth import get_user_model
    from django.db.models import Sum
    from django.db.models.functions import Coalesce
    from archivebox.core.models import ArchiveResult, Snapshot

    config = get_config()
    User = get_user_model()

    print("[green]\\[*] Scanning archive main index...[/green]")
    print(f"[yellow]   {out_dir}/*[/yellow]")
    num_bytes, num_dirs, num_files = get_dir_size(out_dir, recursive=False, pattern="index.")
    size = printable_filesize(num_bytes)
    print(f"    Index size: {size} across {num_files} files")
    print()

    snapshots_qs = Snapshot.objects.all()
    num_sql_links = snapshots_qs.count()
    archive_dir = CONSTANTS.ARCHIVE_DIR
    legacy_snapshot_dirs = []
    if archive_dir.exists():
        legacy_snapshot_dirs = [
            entry for entry in archive_dir.iterdir() if entry.is_dir() and not entry.is_symlink() and Snapshot.is_legacy_archive_dir(entry)
        ]
    from archivebox.misc.db import database_display_location, is_postgres

    index_location = database_display_location() if is_postgres() else CONSTANTS.SQL_INDEX_FILENAME
    print(f"    > SQL Main Index: {num_sql_links} links".ljust(36), f"(found in {index_location})")
    print(f"    > JSON Link Details: {len(legacy_snapshot_dirs)} links".ljust(36), f"(found in {archive_dir.name}/*/index.json)")
    print()
    print("[green]\\[*] Scanning archive data directories...[/green]")
    users_dir = CONSTANTS.USERS_DIR
    # The current users layout is nested below archive/, so scanning both
    # archive/ and archive/users/ recursively counts every current snapshot
    # twice. A single archive root includes both legacy and current layouts.
    scan_roots = [archive_dir] if archive_dir.exists() else []
    scan_roots_display = ", ".join(str(root) for root in scan_roots) if scan_roots else str(archive_dir)
    print(f"[yellow]   {scan_roots_display}[/yellow]")
    do_precise_fs_scan = num_sql_links <= MAX_STATUS_FS_DIR_SCAN
    if do_precise_fs_scan:
        num_bytes = num_dirs = num_files = 0
        for root in scan_roots:
            root_bytes, root_dirs, root_files = get_dir_size(root)
            num_bytes += root_bytes
            num_dirs += root_dirs
            num_files += root_files
    else:
        num_bytes = snapshots_qs.aggregate(total=Coalesce(Sum("output_size"), 0))["total"] or 0
        num_dirs = 0
        num_files = ArchiveResult.objects.exclude(output_files__in=["", "{}"]).count()
    size = printable_filesize(num_bytes)
    if do_precise_fs_scan:
        print(f"    Size: {size} across {num_files} files in {num_dirs} directories")
    else:
        print(f"    Size: {size} across {num_files} DB-tracked output records")

    # Use DB as source of truth for snapshot status
    num_indexed = num_sql_links
    num_archived = snapshots_qs.filter(status=Snapshot.StatusChoices.SEALED).count()
    num_unarchived = max(num_indexed - num_archived, 0)
    print(f"    > indexed: {num_indexed}".ljust(36), "(total snapshots in DB)")
    print(f"      > archived: {num_archived}".ljust(36), "(snapshots with archived content)")
    print(f"      > unarchived: {num_unarchived}".ljust(36), "(snapshots pending archiving)")

    # Count snapshot directories on filesystem across both legacy and current layouts.
    if do_precise_fs_scan:
        links = list(snapshots_qs)
        expected_snapshot_dirs = {str(Path(snapshot.output_dir).resolve()) for snapshot in links if Path(snapshot.output_dir).exists()}
        discovered_snapshot_dirs = {str(entry.resolve()) for entry in legacy_snapshot_dirs}

        if users_dir.exists():
            discovered_snapshot_dirs.update(
                str(entry.resolve()) for entry in users_dir.glob(f"*/{CONSTANTS.SNAPSHOTS_DIR_NAME}/*/*/*") if entry.is_dir()
            )

        orphaned_dirs = sorted(discovered_snapshot_dirs - expected_snapshot_dirs)
        num_present = len(discovered_snapshot_dirs)
        num_valid = len(discovered_snapshot_dirs & expected_snapshot_dirs)
    else:
        orphaned_dirs = []
        num_present = num_archived
        num_valid = num_archived
    print()
    print(f"    > present: {num_present}".ljust(36), "(snapshot directories on disk)")
    print(f"      > [green]valid:[/green] {num_valid}".ljust(36), "               (directories with matching DB entry)")

    num_orphaned = len(orphaned_dirs)
    print(f"      > [red]orphaned:[/red] {num_orphaned}".ljust(36), "         (directories without matching DB entry)")

    if num_indexed:
        print("    [violet]Hint:[/violet] You can list snapshots by status like so:")
        print("        [green]archivebox list --status=<status>  (e.g. sealed, queued, etc.)[/green]")

    if orphaned_dirs:
        print("    [violet]Hint:[/violet] To automatically import orphaned data directories into the main index, run:")
        print("        [green]archivebox update[/green]")

    print()
    print("[green]\\[*] Scanning recent archive changes and user logins:[/green]")
    print(f"[yellow]   {CONSTANTS.LOGS_DIR}/*[/yellow]")
    admin_users = User.objects.filter(is_superuser=True).exclude(username="system")
    users = [user.get_username() for user in admin_users]
    print(f"    UI users {len(users)}: {', '.join(users)}")
    last_login = admin_users.order_by("last_login").last()
    if last_login:
        print(f"    Last UI login: {last_login.get_username()} @ {str(last_login.last_login)[:16]}")
    last_downloaded = Snapshot.objects.order_by("downloaded_at").last()
    if last_downloaded:
        print(f"    Last changes: {str(last_downloaded.downloaded_at)[:16]}")

    if not users:
        from archivebox.core.routes_util import build_admin_url

        print()
        print("    [violet]Hint:[/violet] Open the Admin UI to create the first admin and finish web setup:")
        print(f"        [green]{build_admin_url('/admin/', config=config)}[/green]")

    print()
    recent_snapshots = snapshots_qs.order_by(
        "-downloaded_at",
        "-modified_at",
    )[:10]
    for snapshot in recent_snapshots:
        if not snapshot.downloaded_at:
            continue
        print(
            (
                "[grey53] "
                f"   > {str(snapshot.downloaded_at)[:16]} "
                f"[{snapshot.num_outputs} {('X', '√')[snapshot.status == Snapshot.StatusChoices.SEALED]} {printable_filesize(snapshot.output_size or 0)}] "
                f'"{snapshot.title}": {snapshot.url}'
                "[/grey53]"
            )[: config.TERM_WIDTH],
        )
    print("[grey53]   ...")


@click.command()
@docstring(status.__doc__)
def main(**kwargs):
    """Print out some info and statistics about the archive collection"""
    status(**kwargs)


if __name__ == "__main__":
    main()
