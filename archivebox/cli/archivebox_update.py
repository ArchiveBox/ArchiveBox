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
    from django.core.management import call_command

    # Run migrations first to ensure DB schema is up-to-date
    print('[*] Checking for pending migrations...')
    try:
        call_command('migrate', '--no-input', verbosity=0)
    except Exception as e:
        print(f'[!] Warning: Migration check failed: {e}')

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

    print('[DEBUG Phase1] Scanning for old directories in archive/...')

    # Scan for real directories only (skip symlinks - they're already migrated)
    all_entries = list(os.scandir(archive_dir))
    print(f'[DEBUG Phase1] Total entries in archive/: {len(all_entries)}')
    entries = [
        (e.stat().st_mtime, e.path)
        for e in all_entries
        if e.is_dir(follow_symlinks=False)  # Skip symlinks
    ]
    entries.sort(reverse=True)  # Newest first
    print(f'[DEBUG Phase1] Real directories (not symlinks): {len(entries)}')
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

        # Ensure snapshot has a valid crawl (migration 0024 may have failed)
        from archivebox.crawls.models import Crawl
        has_valid_crawl = False
        if snapshot.crawl_id:
            # Check if the crawl actually exists
            has_valid_crawl = Crawl.objects.filter(id=snapshot.crawl_id).exists()

        if not has_valid_crawl:
            # Create a new crawl (created_by will default to system user)
            crawl = Crawl.objects.create(urls=snapshot.url)
            # Use queryset update to avoid triggering save() hooks
            from archivebox.core.models import Snapshot as SnapshotModel
            SnapshotModel.objects.filter(pk=snapshot.pk).update(crawl=crawl)
            # Refresh the instance
            snapshot.crawl = crawl
            snapshot.crawl_id = crawl.id
            print(f"[DEBUG Phase1] Created missing crawl for snapshot {str(snapshot.id)[:8]}")

        # Check if needs migration (0.8.x → 0.9.x)
        print(f"[DEBUG Phase1] Snapshot {str(snapshot.id)[:8]}: fs_version={snapshot.fs_version}, needs_migration={snapshot.fs_migration_needed}")
        if snapshot.fs_migration_needed:
            try:
                # Calculate paths using actual directory (entry_path), not snapshot.timestamp
                # because snapshot.timestamp might be truncated
                old_dir = entry_path
                new_dir = snapshot.get_storage_path_for_version('0.9.0')
                print(f"[DEBUG Phase1] Migrating {old_dir.name} → {new_dir}")

                # Manually migrate files
                if not new_dir.exists() and old_dir.exists():
                    new_dir.mkdir(parents=True, exist_ok=True)
                    import shutil
                    file_count = 0
                    for old_file in old_dir.rglob('*'):
                        if old_file.is_file():
                            rel_path = old_file.relative_to(old_dir)
                            new_file = new_dir / rel_path
                            if not new_file.exists():
                                new_file.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(old_file, new_file)
                                file_count += 1
                    print(f"[DEBUG Phase1] Copied {file_count} files")

                # Update only fs_version field using queryset update (bypasses validation)
                from archivebox.core.models import Snapshot as SnapshotModel
                SnapshotModel.objects.filter(pk=snapshot.pk).update(fs_version='0.9.0')

                # Commit the transaction
                transaction.commit()

                # Cleanup: delete old dir and create symlink
                if old_dir.exists() and old_dir != new_dir:
                    snapshot._cleanup_old_migration_dir(old_dir, new_dir)

                stats['migrated'] += 1
                print(f"    [{stats['processed']}] Migrated: {entry_path.name}")
            except Exception as e:
                stats['skipped'] += 1
                print(f"    [{stats['processed']}] Skipped (error: {e}): {entry_path.name}")
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
    for snapshot in Snapshot.objects.select_related('crawl').order_by('-bookmarked_at').iterator(chunk_size=batch_size):
        stats['processed'] += 1

        # Skip snapshots with missing crawl references (orphaned by migration errors)
        if not snapshot.crawl_id:
            continue

        try:
            print(f"[DEBUG Phase2] Snapshot {str(snapshot.id)[:8]}: fs_version={snapshot.fs_version}, needs_migration={snapshot.fs_migration_needed}")

            # Check if snapshot has a directory on disk
            from pathlib import Path
            output_dir = Path(snapshot.output_dir)
            has_directory = output_dir.exists() and output_dir.is_dir()

            # Only reconcile if directory exists (don't create empty directories for orphans)
            if has_directory:
                snapshot.reconcile_with_index_json()

            # Clean up invalid field values from old migrations
            if not isinstance(snapshot.current_step, int):
                snapshot.current_step = 0

            # If still needs migration, it's an orphan (no directory on disk)
            # Mark it as migrated to prevent save() from triggering filesystem migration
            if snapshot.fs_migration_needed:
                if has_directory:
                    print(f"[DEBUG Phase2] WARNING: Snapshot {str(snapshot.id)[:8]} has directory but still needs migration")
                else:
                    print(f"[DEBUG Phase2] Orphan snapshot {str(snapshot.id)[:8]} - marking as migrated without filesystem operation")
                # Use queryset update to set fs_version without triggering save() hooks
                from archivebox.core.models import Snapshot as SnapshotModel
                SnapshotModel.objects.filter(pk=snapshot.pk).update(fs_version='0.9.0')
                snapshot.fs_version = '0.9.0'

            # Queue for archiving (state machine will handle it)
            snapshot.status = Snapshot.StatusChoices.QUEUED
            snapshot.retry_at = timezone.now()
            snapshot.save()

            stats['reconciled'] += 1 if has_directory else 0
            stats['queued'] += 1
        except Exception as e:
            # Skip snapshots that can't be processed (e.g., missing crawl)
            print(f"    [!] Skipping snapshot {snapshot.id}: {e}")
            continue

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

    for snapshot in snapshots.select_related('crawl').iterator(chunk_size=batch_size):
        stats['processed'] += 1

        # Skip snapshots with missing crawl references
        if not snapshot.crawl_id:
            continue

        try:
            # Reconcile index.json with DB
            snapshot.reconcile_with_index_json()

            # Clean up invalid field values from old migrations
            if not isinstance(snapshot.current_step, int):
                snapshot.current_step = 0

            # Queue for archiving
            snapshot.status = Snapshot.StatusChoices.QUEUED
            snapshot.retry_at = timezone.now()
            snapshot.save()

            stats['reconciled'] += 1
            stats['queued'] += 1
        except Exception as e:
            # Skip snapshots that can't be processed
            print(f"    [!] Skipping snapshot {snapshot.id}: {e}")
            continue

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
