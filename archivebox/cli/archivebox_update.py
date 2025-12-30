#!/usr/bin/env python3

__package__ = 'archivebox.cli'

import os
import time
import rich_click as click

from typing import Iterable
from pathlib import Path

from archivebox.misc.util import enforce_types, docstring


@enforce_types
def update(filter_patterns: Iterable[str] = (),
          filter_type: str = 'exact',
          before: float | None = None,
          after: float | None = None,
          resume: str | None = None,
          batch_size: int = 100,
          continuous: bool = False) -> None:
    """
    Update snapshots: migrate old dirs, reconcile DB, and re-queue for archiving.

    Three-phase operation (without filters):
    - Phase 1: Drain old archive/ dirs by moving to new fs location (0.8.x → 0.9.x)
    - Phase 2: O(n) scan over entire DB from most recent to least recent
    - No orphan scans needed (trust 1:1 mapping between DB and filesystem after phase 1)

    With filters: Only phase 2 (DB query), no filesystem operations.
    Without filters: All phases (full update).
    """

    from rich import print
    from archivebox.config.django import setup_django
    setup_django()

    from archivebox.core.models import Snapshot
    from django.utils import timezone

    while True:
        if filter_patterns or before or after:
            # Filtered mode: query DB only
            print('[*] Processing filtered snapshots from database...')
            stats = process_filtered_snapshots(
                filter_patterns=filter_patterns,
                filter_type=filter_type,
                before=before,
                after=after,
                batch_size=batch_size
            )
            print_stats(stats)
        else:
            # Full mode: drain old dirs + process DB
            stats_combined = {'phase1': {}, 'phase2': {}}

            print('[*] Phase 1: Draining old archive/ directories (0.8.x → 0.9.x migration)...')
            stats_combined['phase1'] = drain_old_archive_dirs(
                resume_from=resume,
                batch_size=batch_size
            )

            print('[*] Phase 2: Processing all database snapshots (most recent first)...')
            stats_combined['phase2'] = process_all_db_snapshots(batch_size=batch_size)

            # Phase 3: Deduplication (disabled for now)
            # print('[*] Phase 3: Deduplicating...')
            # stats_combined['deduplicated'] = Snapshot.find_and_merge_duplicates()

            print_combined_stats(stats_combined)

        if not continuous:
            break

        print('[yellow]Sleeping 60s before next pass...[/yellow]')
        time.sleep(60)
        resume = None


def drain_old_archive_dirs(resume_from: str = None, batch_size: int = 100) -> dict:
    """
    Drain old archive/ directories (0.8.x → 0.9.x migration).

    Only processes real directories (skips symlinks - those are already migrated).
    For each old dir found in archive/:
      1. Load or create DB snapshot
      2. Trigger fs migration on save() to move to data/users/{user}/...
      3. Leave symlink in archive/ pointing to new location

    After this drains, archive/ should only contain symlinks and we can trust
    1:1 mapping between DB and filesystem.
    """
    from archivebox.core.models import Snapshot
    from archivebox.config import CONSTANTS
    from django.db import transaction

    stats = {'processed': 0, 'migrated': 0, 'skipped': 0, 'invalid': 0}

    archive_dir = CONSTANTS.ARCHIVE_DIR
    if not archive_dir.exists():
        return stats

    print('[*] Scanning for old directories in archive/...')

    # Scan for real directories only (skip symlinks - they're already migrated)
    entries = [
        (e.stat().st_mtime, e.path)
        for e in os.scandir(archive_dir)
        if e.is_dir(follow_symlinks=False)  # Skip symlinks
    ]
    entries.sort(reverse=True)  # Newest first
    print(f'[*] Found {len(entries)} old directories to drain')

    for mtime, entry_path in entries:
        entry_path = Path(entry_path)

        # Resume from timestamp if specified
        if resume_from and entry_path.name < resume_from:
            continue

        stats['processed'] += 1

        # Try to load existing snapshot from DB
        snapshot = Snapshot.load_from_directory(entry_path)

        if not snapshot:
            # Not in DB - create new snapshot record
            snapshot = Snapshot.create_from_directory(entry_path)
            if not snapshot:
                # Invalid directory - move to invalid/
                Snapshot.move_directory_to_invalid(entry_path)
                stats['invalid'] += 1
                print(f"    [{stats['processed']}] Invalid: {entry_path.name}")
                continue

        # Check if needs migration (0.8.x → 0.9.x)
        if snapshot.fs_migration_needed:
            snapshot.save()  # Triggers migration + creates symlink
            stats['migrated'] += 1
            print(f"    [{stats['processed']}] Migrated: {entry_path.name}")
        else:
            stats['skipped'] += 1

        if stats['processed'] % batch_size == 0:
            transaction.commit()

    transaction.commit()
    return stats


def process_all_db_snapshots(batch_size: int = 100) -> dict:
    """
    O(n) scan over entire DB from most recent to least recent.

    For each snapshot:
      1. Reconcile index.json with DB (merge titles, tags, archive results)
      2. Queue for archiving (state machine will handle it)

    No orphan detection needed - we trust 1:1 mapping between DB and filesystem
    after Phase 1 has drained all old archive/ directories.
    """
    from archivebox.core.models import Snapshot
    from django.db import transaction
    from django.utils import timezone

    stats = {'processed': 0, 'reconciled': 0, 'queued': 0}

    total = Snapshot.objects.count()
    print(f'[*] Processing {total} snapshots from database (most recent first)...')

    # Process from most recent to least recent
    for snapshot in Snapshot.objects.order_by('-bookmarked_at').iterator(chunk_size=batch_size):
        # Reconcile index.json with DB
        snapshot.reconcile_with_index_json()

        # Queue for archiving (state machine will handle it)
        snapshot.status = Snapshot.StatusChoices.QUEUED
        snapshot.retry_at = timezone.now()
        snapshot.save()

        stats['reconciled'] += 1
        stats['queued'] += 1
        stats['processed'] += 1

        if stats['processed'] % batch_size == 0:
            transaction.commit()
            print(f"    [{stats['processed']}/{total}] Processed...")

    transaction.commit()
    return stats


def process_filtered_snapshots(
    filter_patterns: Iterable[str],
    filter_type: str,
    before: float | None,
    after: float | None,
    batch_size: int
) -> dict:
    """Process snapshots matching filters (DB query only)."""
    from archivebox.core.models import Snapshot
    from django.db import transaction
    from django.utils import timezone
    from datetime import datetime

    stats = {'processed': 0, 'reconciled': 0, 'queued': 0}

    snapshots = Snapshot.objects.all()

    if filter_patterns:
        snapshots = Snapshot.objects.filter_by_patterns(list(filter_patterns), filter_type)

    if before:
        snapshots = snapshots.filter(bookmarked_at__lt=datetime.fromtimestamp(before))
    if after:
        snapshots = snapshots.filter(bookmarked_at__gt=datetime.fromtimestamp(after))

    total = snapshots.count()
    print(f'[*] Found {total} matching snapshots')

    for snapshot in snapshots.iterator(chunk_size=batch_size):
        # Reconcile index.json with DB
        snapshot.reconcile_with_index_json()

        # Queue for archiving
        snapshot.status = Snapshot.StatusChoices.QUEUED
        snapshot.retry_at = timezone.now()
        snapshot.save()

        stats['reconciled'] += 1
        stats['queued'] += 1
        stats['processed'] += 1

        if stats['processed'] % batch_size == 0:
            transaction.commit()
            print(f"    [{stats['processed']}/{total}] Processed...")

    transaction.commit()
    return stats


def print_stats(stats: dict):
    """Print statistics for filtered mode."""
    from rich import print

    print(f"""
[green]Update Complete[/green]
  Processed:   {stats['processed']}
  Reconciled:  {stats['reconciled']}
  Queued:      {stats['queued']}
""")


def print_combined_stats(stats_combined: dict):
    """Print statistics for full mode."""
    from rich import print

    s1 = stats_combined['phase1']
    s2 = stats_combined['phase2']

    print(f"""
[green]Archive Update Complete[/green]

Phase 1 (Drain Old Dirs):
  Checked:     {s1.get('processed', 0)}
  Migrated:    {s1.get('migrated', 0)}
  Skipped:     {s1.get('skipped', 0)}
  Invalid:     {s1.get('invalid', 0)}

Phase 2 (Process DB):
  Processed:   {s2.get('processed', 0)}
  Reconciled:  {s2.get('reconciled', 0)}
  Queued:      {s2.get('queued', 0)}
""")


@click.command()
@click.option('--resume', type=str, help='Resume from timestamp')
@click.option('--before', type=float, help='Only snapshots before timestamp')
@click.option('--after', type=float, help='Only snapshots after timestamp')
@click.option('--filter-type', '-t', type=click.Choice(['exact', 'substring', 'regex', 'domain', 'tag', 'timestamp']), default='exact')
@click.option('--batch-size', type=int, default=100, help='Commit every N snapshots')
@click.option('--continuous', is_flag=True, help='Run continuously as background worker')
@click.argument('filter_patterns', nargs=-1)
@docstring(update.__doc__)
def main(**kwargs):
    update(**kwargs)


if __name__ == '__main__':
    main()
