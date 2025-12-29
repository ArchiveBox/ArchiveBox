# Lazy Filesystem Migration System - Implementation TODO

## Architecture Decision: DB as Single Source of Truth

**Key Principle**: Only `archivebox update` scans the filesystem (for migration/import). All other commands query the database exclusively.

- ✅ `archivebox status` - Query DB only (count by status field)
- ✅ `archivebox search` - Query DB only (filter by URL/tags/etc)
- ✅ `archivebox remove` - Query DB + delete directories
- ⚠️ `archivebox update` - **ONLY command that scans filesystem** (for orphan import + migration)
- ✅ `archivebox init` - Simplified: just apply migrations, no folder scanning

---

## Status: What Already Exists

### ✅ Core Migration Infrastructure (in `archivebox/core/models.py`)

**Lines 348-367: Migration on `save()` with transaction wrapper**
- Automatically detects if `fs_migration_needed`
- Walks migration chain: 0.7.0 → 0.8.0 → 0.9.0
- Calls `_fs_migrate_from_X_to_Y()` methods
- Updates `fs_version` field within transaction

**Lines 393-419: Migration helper methods**
- `_fs_current_version()` - Gets current ArchiveBox version (normalizes to x.x.0)
- `fs_migration_needed` property - Checks if migration needed
- `_fs_next_version()` - Returns next version in chain
- `_fs_migrate_from_0_7_0_to_0_8_0()` - No-op (same layout)
- `_fs_migrate_from_0_8_0_to_0_9_0()` - **Placeholder (currently no-op at line 427)** ← NEEDS IMPLEMENTATION

**Lines 540-542: `output_dir` property**
- Currently: `return str(CONSTANTS.ARCHIVE_DIR / self.timestamp)`
- Needs: Check `fs_version`, handle symlinks for backwards compat

**Line 311: `fs_version` field**
- CharField tracking filesystem version per snapshot
- Default is current ArchiveBox version

**Lines 266-267: Timestamp uniqueness logic EXISTS**
```python
while self.filter(timestamp=timestamp).exists():
    timestamp = str(float(timestamp) + 1.0)
```
Already implemented in `create_or_update_from_dict()` at line 241!

**Lines 120-133: SnapshotQuerySet with `filter_by_patterns()`**
- Already supports filtering by exact/substring/regex/domain/tag/timestamp

**archivebox/misc/jsonl.py:**
- Line 252: `get_or_create_snapshot()` - Creates snapshot from JSONL record
- Line 281: Uses `Snapshot.objects.create_or_update_from_dict()` internally

### ✅ Current `archivebox update` Implementation (archivebox/cli/archivebox_update.py)

**Lines 36-102:**
- Filters snapshots from DB using `filter_by_patterns()`
- Applies before/after timestamp filters
- Queues snapshots via status update
- Starts Orchestrator to process queued snapshots

**Current behavior:**
- Only queries DB, never scans filesystem ← NEEDS TO BE FIXED
- No orphan detection ← NEEDS TO BE ADDED
- No reconciliation ← NEEDS TO BE ADDED
- No migration triggering ← save() does this automatically

---

## What Needs Implementation

### Phase 1: Add Methods to Snapshot Model

File: `archivebox/core/models.py`

Add these methods after the existing migration methods (around line 457):

```python
# =========================================================================
# Path Calculation and Migration Helpers
# =========================================================================

@staticmethod
def extract_domain_from_url(url: str) -> str:
    """
    Extract domain from URL for 0.9.x path structure.
    Uses full hostname with sanitized special chars.

    Examples:
        https://example.com:8080 → example.com_8080
        https://sub.example.com → sub.example.com
        file:///path → localhost
        data:text/html → data
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)

        if parsed.scheme in ('http', 'https'):
            if parsed.port:
                return f"{parsed.hostname}_{parsed.port}".replace(':', '_')
            return parsed.hostname or 'unknown'
        elif parsed.scheme == 'file':
            return 'localhost'
        elif parsed.scheme:
            return parsed.scheme
        else:
            return 'unknown'
    except Exception:
        return 'unknown'

def get_storage_path_for_version(self, version: str) -> Path:
    """
    Calculate storage path for specific filesystem version.
    Centralizes path logic so it's reusable.

    0.7.x/0.8.x: archive/{timestamp}
    0.9.x: users/{username}/snapshots/YYYYMMDD/{domain}/{uuid}/
    """
    from datetime import datetime

    if version in ('0.7.0', '0.8.0'):
        return CONSTANTS.ARCHIVE_DIR / self.timestamp

    elif version in ('0.9.0', '1.0.0'):
        username = self.created_by.username if self.created_by else 'unknown'

        # Use created_at for date grouping (fallback to timestamp)
        if self.created_at:
            date_str = self.created_at.strftime('%Y%m%d')
        else:
            date_str = datetime.fromtimestamp(float(self.timestamp)).strftime('%Y%m%d')

        domain = self.extract_domain_from_url(self.url)

        return (
            CONSTANTS.DATA_DIR / 'users' / username / 'snapshots' /
            date_str / domain / str(self.id)
        )
    else:
        # Unknown version - use current
        return self.get_storage_path_for_version(self._fs_current_version())

# =========================================================================
# Loading and Creation from Filesystem (Used by archivebox update ONLY)
# =========================================================================

@classmethod
def load_from_directory(cls, snapshot_dir: Path) -> Optional['Snapshot']:
    """
    Load existing Snapshot from DB by reading index.json.

    Reads index.json, extracts url+timestamp, queries DB.
    Returns existing Snapshot or None if not found/invalid.
    Does NOT create new snapshots.

    ONLY used by: archivebox update (for orphan detection)
    """
    import json

    index_path = snapshot_dir / 'index.json'
    if not index_path.exists():
        return None

    try:
        with open(index_path) as f:
            data = json.load(f)
    except:
        return None

    url = data.get('url')
    if not url:
        return None

    # Get timestamp - prefer index.json, fallback to folder name
    timestamp = cls._select_best_timestamp(
        index_timestamp=data.get('timestamp'),
        folder_name=snapshot_dir.name
    )

    if not timestamp:
        return None

    # Look up existing
    try:
        return cls.objects.get(url=url, timestamp=timestamp)
    except cls.DoesNotExist:
        return None
    except cls.MultipleObjectsReturned:
        # Should not happen with unique constraint
        return cls.objects.filter(url=url, timestamp=timestamp).first()

@classmethod
def create_from_directory(cls, snapshot_dir: Path) -> Optional['Snapshot']:
    """
    Create new Snapshot from orphaned directory.

    Validates timestamp, ensures uniqueness.
    Returns new UNSAVED Snapshot or None if invalid.

    ONLY used by: archivebox update (for orphan import)
    """
    import json
    from archivebox.base_models.models import get_or_create_system_user_pk

    index_path = snapshot_dir / 'index.json'
    if not index_path.exists():
        return None

    try:
        with open(index_path) as f:
            data = json.load(f)
    except:
        return None

    url = data.get('url')
    if not url:
        return None

    # Get and validate timestamp
    timestamp = cls._select_best_timestamp(
        index_timestamp=data.get('timestamp'),
        folder_name=snapshot_dir.name
    )

    if not timestamp:
        return None

    # Ensure uniqueness (reuses existing logic from create_or_update_from_dict)
    timestamp = cls._ensure_unique_timestamp(url, timestamp)

    # Detect version
    fs_version = cls._detect_fs_version_from_index(data)

    return cls(
        url=url,
        timestamp=timestamp,
        title=data.get('title', ''),
        fs_version=fs_version,
        created_by_id=get_or_create_system_user_pk(),
    )

@staticmethod
def _select_best_timestamp(index_timestamp: str, folder_name: str) -> Optional[str]:
    """
    Select best timestamp from index.json vs folder name.

    Validates range (1995-2035).
    Prefers index.json if valid.
    """
    def is_valid_timestamp(ts):
        try:
            ts_int = int(float(ts))
            # 1995-01-01 to 2035-12-31
            return 788918400 <= ts_int <= 2082758400
        except:
            return False

    index_valid = is_valid_timestamp(index_timestamp) if index_timestamp else False
    folder_valid = is_valid_timestamp(folder_name)

    if index_valid:
        return str(int(float(index_timestamp)))
    elif folder_valid:
        return str(int(float(folder_name)))
    else:
        return None

@classmethod
def _ensure_unique_timestamp(cls, url: str, timestamp: str) -> str:
    """
    Ensure timestamp is globally unique.
    If collision with different URL, increment by 1 until unique.

    NOTE: Logic already exists in create_or_update_from_dict (line 266-267)
    This is just an extracted, reusable version.
    """
    while cls.objects.filter(timestamp=timestamp).exclude(url=url).exists():
        timestamp = str(int(float(timestamp)) + 1)
    return timestamp

@staticmethod
def _detect_fs_version_from_index(data: dict) -> str:
    """
    Detect fs_version from index.json structure.

    - Has fs_version field: use it
    - Has history dict: 0.7.0
    - Has archive_results list: 0.8.0
    - Default: 0.7.0
    """
    if 'fs_version' in data:
        return data['fs_version']
    if 'history' in data and 'archive_results' not in data:
        return '0.7.0'
    if 'archive_results' in data:
        return '0.8.0'
    return '0.7.0'

# =========================================================================
# Index.json Reconciliation
# =========================================================================

def reconcile_with_index_json(self):
    """
    Merge index.json with DB. DB is source of truth.

    - Title: longest non-URL
    - Tags: union
    - ArchiveResults: keep both (by extractor+start_ts)

    Writes back in 0.9.x format.

    Used by: archivebox update (to sync index.json with DB)
    """
    import json

    index_path = Path(self.output_dir) / 'index.json'

    index_data = {}
    if index_path.exists():
        try:
            with open(index_path) as f:
                index_data = json.load(f)
        except:
            pass

    # Merge title
    self._merge_title_from_index(index_data)

    # Merge tags
    self._merge_tags_from_index(index_data)

    # Merge ArchiveResults
    self._merge_archive_results_from_index(index_data)

    # Write back
    self.write_index_json()

def _merge_title_from_index(self, index_data: dict):
    """Merge title - prefer longest non-URL title."""
    index_title = index_data.get('title', '').strip()
    db_title = self.title or ''

    candidates = [t for t in [index_title, db_title] if t and t != self.url]
    if candidates:
        best_title = max(candidates, key=len)
        if self.title != best_title:
            self.title = best_title

def _merge_tags_from_index(self, index_data: dict):
    """Merge tags - union of both sources."""
    from django.db import transaction

    index_tags = set(index_data.get('tags', '').split(',')) if index_data.get('tags') else set()
    index_tags = {t.strip() for t in index_tags if t.strip()}

    db_tags = set(self.tags.values_list('name', flat=True))

    new_tags = index_tags - db_tags
    if new_tags:
        with transaction.atomic():
            for tag_name in new_tags:
                tag, _ = Tag.objects.get_or_create(name=tag_name)
                self.tags.add(tag)

def _merge_archive_results_from_index(self, index_data: dict):
    """Merge ArchiveResults - keep both (by extractor+start_ts)."""
    existing = {
        (ar.extractor, ar.start_ts): ar
        for ar in ArchiveResult.objects.filter(snapshot=self)
    }

    # Handle 0.8.x format (archive_results list)
    for result_data in index_data.get('archive_results', []):
        self._create_archive_result_if_missing(result_data, existing)

    # Handle 0.7.x format (history dict)
    if 'history' in index_data and isinstance(index_data['history'], dict):
        for extractor, result_list in index_data['history'].items():
            if isinstance(result_list, list):
                for result_data in result_list:
                    result_data['extractor'] = extractor
                    self._create_archive_result_if_missing(result_data, existing)

def _create_archive_result_if_missing(self, result_data: dict, existing: dict):
    """Create ArchiveResult if not already in DB."""
    from dateutil import parser
    import json

    extractor = result_data.get('extractor', '')
    if not extractor:
        return

    start_ts = None
    if result_data.get('start_ts'):
        try:
            start_ts = parser.parse(result_data['start_ts'])
        except:
            pass

    if (extractor, start_ts) in existing:
        return

    try:
        end_ts = None
        if result_data.get('end_ts'):
            try:
                end_ts = parser.parse(result_data['end_ts'])
            except:
                pass

        ArchiveResult.objects.create(
            snapshot=self,
            extractor=extractor,
            status=result_data.get('status', 'failed'),
            output_str=result_data.get('output', ''),
            cmd=result_data.get('cmd', []),
            pwd=result_data.get('pwd', str(self.output_dir)),
            start_ts=start_ts,
            end_ts=end_ts,
            created_by=self.created_by,
        )
    except:
        pass

def write_index_json(self):
    """Write index.json in 0.9.x format."""
    import json

    index_path = Path(self.output_dir) / 'index.json'

    data = {
        'url': self.url,
        'timestamp': self.timestamp,
        'title': self.title or '',
        'tags': ','.join(sorted(self.tags.values_list('name', flat=True))),
        'fs_version': self.fs_version,
        'bookmarked_at': self.bookmarked_at.isoformat() if self.bookmarked_at else None,
        'created_at': self.created_at.isoformat() if self.created_at else None,
        'archive_results': [
            {
                'extractor': ar.extractor,
                'status': ar.status,
                'start_ts': ar.start_ts.isoformat() if ar.start_ts else None,
                'end_ts': ar.end_ts.isoformat() if ar.end_ts else None,
                'output': ar.output_str or '',
                'cmd': ar.cmd if isinstance(ar.cmd, list) else [],
                'pwd': ar.pwd,
            }
            for ar in ArchiveResult.objects.filter(snapshot=self).order_by('start_ts')
        ],
    }

    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)

# =========================================================================
# Snapshot Utilities
# =========================================================================

@staticmethod
def move_directory_to_invalid(snapshot_dir: Path):
    """
    Move invalid directory to data/invalid/YYYYMMDD/.

    Used by: archivebox update (when encountering invalid directories)
    """
    from datetime import datetime
    import shutil

    invalid_dir = CONSTANTS.DATA_DIR / 'invalid' / datetime.now().strftime('%Y%m%d')
    invalid_dir.mkdir(parents=True, exist_ok=True)

    dest = invalid_dir / snapshot_dir.name
    counter = 1
    while dest.exists():
        dest = invalid_dir / f"{snapshot_dir.name}_{counter}"
        counter += 1

    try:
        shutil.move(str(snapshot_dir), str(dest))
    except:
        pass

@classmethod
def find_and_merge_duplicates(cls) -> int:
    """
    Find and merge snapshots with same url:timestamp.
    Returns count of duplicate sets merged.

    Used by: archivebox update (Phase 3: deduplication)
    """
    from django.db.models import Count

    duplicates = (
        cls.objects
        .values('url', 'timestamp')
        .annotate(count=Count('id'))
        .filter(count__gt=1)
    )

    merged = 0
    for dup in duplicates.iterator():
        snapshots = list(
            cls.objects
            .filter(url=dup['url'], timestamp=dup['timestamp'])
            .order_by('created_at')  # Keep oldest
        )

        if len(snapshots) > 1:
            try:
                cls._merge_snapshots(snapshots)
                merged += 1
            except:
                pass

    return merged

@classmethod
def _merge_snapshots(cls, snapshots: list['Snapshot']):
    """
    Merge exact duplicates.
    Keep oldest, union files + ArchiveResults.
    """
    import shutil

    keeper = snapshots[0]
    duplicates = snapshots[1:]

    keeper_dir = Path(keeper.output_dir)

    for dup in duplicates:
        dup_dir = Path(dup.output_dir)

        # Merge files
        if dup_dir.exists() and dup_dir != keeper_dir:
            for dup_file in dup_dir.rglob('*'):
                if not dup_file.is_file():
                    continue

                rel = dup_file.relative_to(dup_dir)
                keeper_file = keeper_dir / rel

                if not keeper_file.exists():
                    keeper_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dup_file, keeper_file)

            try:
                shutil.rmtree(dup_dir)
            except:
                pass

        # Merge tags
        for tag in dup.tags.all():
            keeper.tags.add(tag)

        # Move ArchiveResults
        ArchiveResult.objects.filter(snapshot=dup).update(snapshot=keeper)

        # Delete
        dup.delete()
```

### Phase 2: Update `output_dir` Property

File: `archivebox/core/models.py` line 540

Replace current implementation:

```python
@cached_property
def output_dir(self):
    """The filesystem path to the snapshot's output directory."""
    import os

    current_path = self.get_storage_path_for_version(self.fs_version)

    if current_path.exists():
        return str(current_path)

    # Check for backwards-compat symlink
    old_path = CONSTANTS.ARCHIVE_DIR / self.timestamp
    if old_path.is_symlink():
        return str(Path(os.readlink(old_path)).resolve())
    elif old_path.exists():
        return str(old_path)

    return str(current_path)
```

### Phase 3: Implement Real Migration

File: `archivebox/core/models.py` line 427

Replace the placeholder `_fs_migrate_from_0_8_0_to_0_9_0()`:

```python
def _fs_migrate_from_0_8_0_to_0_9_0(self):
    """
    Migrate from flat to nested structure.

    0.8.x: archive/{timestamp}/
    0.9.x: users/{user}/snapshots/YYYYMMDD/{domain}/{uuid}/

    Transaction handling:
    1. Copy files INSIDE transaction
    2. Create symlink INSIDE transaction
    3. Update fs_version INSIDE transaction (done by save())
    4. Exit transaction (DB commit)
    5. Delete old files OUTSIDE transaction (after commit)
    """
    import shutil
    from django.db import transaction

    old_dir = self.get_storage_path_for_version('0.8.0')
    new_dir = self.get_storage_path_for_version('0.9.0')

    if not old_dir.exists() or old_dir == new_dir or new_dir.exists():
        return

    new_dir.mkdir(parents=True, exist_ok=True)

    # Copy all files (idempotent)
    for old_file in old_dir.rglob('*'):
        if not old_file.is_file():
            continue

        rel_path = old_file.relative_to(old_dir)
        new_file = new_dir / rel_path

        # Skip if already copied
        if new_file.exists() and new_file.stat().st_size == old_file.stat().st_size:
            continue

        new_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_file, new_file)

    # Verify all copied
    old_files = {f.relative_to(old_dir): f.stat().st_size
                 for f in old_dir.rglob('*') if f.is_file()}
    new_files = {f.relative_to(new_dir): f.stat().st_size
                 for f in new_dir.rglob('*') if f.is_file()}

    if old_files.keys() != new_files.keys():
        missing = old_files.keys() - new_files.keys()
        raise Exception(f"Migration incomplete: missing {missing}")

    # Create backwards-compat symlink (INSIDE transaction)
    symlink_path = CONSTANTS.ARCHIVE_DIR / self.timestamp
    if symlink_path.is_symlink():
        symlink_path.unlink()

    if not symlink_path.exists() or symlink_path == old_dir:
        symlink_path.symlink_to(new_dir, target_is_directory=True)

    # Schedule old directory deletion AFTER transaction commits
    transaction.on_commit(lambda: self._cleanup_old_migration_dir(old_dir))

def _cleanup_old_migration_dir(self, old_dir: Path):
    """
    Delete old directory after successful migration.
    Called via transaction.on_commit() after DB commit succeeds.
    """
    import shutil
    import logging

    if old_dir.exists() and not old_dir.is_symlink():
        try:
            shutil.rmtree(old_dir)
        except Exception as e:
            # Log but don't raise - migration succeeded, this is just cleanup
            logging.getLogger('archivebox.migration').warning(
                f"Could not remove old migration directory {old_dir}: {e}"
            )
```

### Phase 4: Add Timestamp Uniqueness Constraint

File: `archivebox/core/models.py` - Add to `Snapshot.Meta` class (around line 330):

```python
class Meta(TypedModelMeta):
    verbose_name = "Snapshot"
    verbose_name_plural = "Snapshots"
    constraints = [
        # Allow same URL in different crawls, but not duplicates within same crawl
        models.UniqueConstraint(fields=['url', 'crawl'], name='unique_url_per_crawl'),
        # Global timestamp uniqueness for 1:1 symlink mapping
        models.UniqueConstraint(fields=['timestamp'], name='unique_timestamp'),
    ]
```

Then create migration:
```bash
python -m archivebox manage makemigrations core
```

### Phase 5: Rewrite `archivebox update`

File: `archivebox/cli/archivebox_update.py`

Replace entire file:

```python
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
    Update snapshots: import orphans, reconcile, and re-run failed extractors.

    Two-phase operation:
    - Phase 1: Scan archive/ for orphaned snapshots (skip symlinks)
    - Phase 2: Process all DB snapshots (reconcile + re-queue for archiving)
    - Phase 3: Deduplicate exact duplicates

    With filters: Only phase 2 (DB query), no filesystem scan.
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
            # Full mode: import orphans + process DB + deduplicate
            stats_combined = {'phase1': {}, 'phase2': {}, 'deduplicated': 0}

            print('[*] Phase 1: Scanning archive/ for orphaned snapshots...')
            stats_combined['phase1'] = import_orphans_from_archive(
                resume_from=resume,
                batch_size=batch_size
            )

            print('[*] Phase 2: Processing all database snapshots...')
            stats_combined['phase2'] = process_all_db_snapshots(batch_size=batch_size)

            print('[*] Phase 3: Deduplicating...')
            stats_combined['deduplicated'] = Snapshot.find_and_merge_duplicates()

            print_combined_stats(stats_combined)

        if not continuous:
            break

        print('[yellow]Sleeping 60s before next pass...[/yellow]')
        time.sleep(60)
        resume = None


def import_orphans_from_archive(resume_from: str = None, batch_size: int = 100) -> dict:
    """
    Scan archive/ for orphaned snapshots.
    Skip symlinks (already migrated).
    Create DB records and trigger migration on save().
    """
    from archivebox.core.models import Snapshot
    from archivebox.config import CONSTANTS
    from django.db import transaction

    stats = {'processed': 0, 'imported': 0, 'migrated': 0, 'invalid': 0}

    archive_dir = CONSTANTS.ARCHIVE_DIR
    if not archive_dir.exists():
        return stats

    print('[*] Scanning and sorting by modification time...')

    # Scan and sort by mtime (newest first)
    # Loading (mtime, path) tuples is fine even for millions (~100MB for 1M entries)
    entries = [
        (e.stat().st_mtime, e.path)
        for e in os.scandir(archive_dir)
        if e.is_dir(follow_symlinks=False)  # Skip symlinks
    ]
    entries.sort(reverse=True)  # Newest first
    print(f'[*] Found {len(entries)} directories to check')

    for mtime, entry_path in entries:
        entry_path = Path(entry_path)

        # Resume from timestamp if specified
        if resume_from and entry_path.name < resume_from:
            continue

        stats['processed'] += 1

        # Check if already in DB
        snapshot = Snapshot.load_from_directory(entry_path)
        if snapshot:
            continue  # Already in DB, skip

        # Not in DB - create orphaned snapshot
        snapshot = Snapshot.create_from_directory(entry_path)
        if not snapshot:
            # Invalid directory
            Snapshot.move_directory_to_invalid(entry_path)
            stats['invalid'] += 1
            print(f"    [{stats['processed']}] Invalid: {entry_path.name}")
            continue

        needs_migration = snapshot.fs_migration_needed

        snapshot.save()  # Creates DB record + triggers migration

        stats['imported'] += 1
        if needs_migration:
            stats['migrated'] += 1
            print(f"    [{stats['processed']}] Imported + migrated: {entry_path.name}")
        else:
            print(f"    [{stats['processed']}] Imported: {entry_path.name}")

        if stats['processed'] % batch_size == 0:
            transaction.commit()

    transaction.commit()
    return stats


def process_all_db_snapshots(batch_size: int = 100) -> dict:
    """
    Process all snapshots in DB.
    Reconcile index.json and queue for archiving.
    """
    from archivebox.core.models import Snapshot
    from django.db import transaction
    from django.utils import timezone

    stats = {'processed': 0, 'reconciled': 0, 'queued': 0}

    total = Snapshot.objects.count()
    print(f'[*] Processing {total} snapshots from database...')

    for snapshot in Snapshot.objects.iterator():
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

    for snapshot in snapshots.iterator():
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

Phase 1 (Import Orphans):
  Checked:     {s1.get('processed', 0)}
  Imported:    {s1.get('imported', 0)}
  Migrated:    {s1.get('migrated', 0)}
  Invalid:     {s1.get('invalid', 0)}

Phase 2 (Process DB):
  Processed:   {s2.get('processed', 0)}
  Reconciled:  {s2.get('reconciled', 0)}
  Queued:      {s2.get('queued', 0)}

Phase 3 (Deduplicate):
  Merged:      {stats_combined['deduplicated']}
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
```

### Phase 6: Simplify `archivebox init`

File: `archivebox/cli/archivebox_init.py`

Remove lines 24, 113-150 (folder status function usage):

```python
# DELETE line 24:
from archivebox.misc.folders import fix_invalid_folder_locations, get_invalid_folders

# DELETE lines 113-150 (folder scanning logic):
# Replace with simple message:
print('    > Run "archivebox update" to import any orphaned snapshot directories')
```

Simplified logic:
- Create directory structure
- Apply migrations
- **Don't scan for orphans** (let `archivebox update` handle it)

### Phase 7: Simplify `archivebox search`

File: `archivebox/cli/archivebox_search.py`

Remove lines 65-96 (all folder status imports and `list_folders()` function):

```python
# DELETE lines 65-96
# DELETE STATUS_CHOICES with 'valid', 'invalid', 'orphaned', 'corrupted', 'unrecognized'

# Keep only: 'indexed', 'archived', 'unarchived'
STATUS_CHOICES = ['indexed', 'archived', 'unarchived']
```

Update `search()` function to query DB directly:

```python
@enforce_types
def search(filter_patterns: list[str] | None=None,
           filter_type: str='substring',
           status: str='indexed',
           before: float | None=None,
           after: float | None=None,
           sort: str | None=None,
           json: bool=False,
           html: bool=False,
           csv: str | None=None,
           with_headers: bool=False):
    """List, filter, and export information about archive entries"""

    from archivebox.core.models import Snapshot

    if with_headers and not (json or html or csv):
        stderr('[X] --with-headers requires --json, --html or --csv\n', color='red')
        raise SystemExit(2)

    # Query DB directly
    snapshots = Snapshot.objects.all()

    if filter_patterns:
        snapshots = Snapshot.objects.filter_by_patterns(list(filter_patterns), filter_type)

    if status == 'archived':
        snapshots = snapshots.filter(downloaded_at__isnull=False)
    elif status == 'unarchived':
        snapshots = snapshots.filter(downloaded_at__isnull=True)
    # 'indexed' = all snapshots (no filter)

    if before:
        from datetime import datetime
        snapshots = snapshots.filter(bookmarked_at__lt=datetime.fromtimestamp(before))
    if after:
        from datetime import datetime
        snapshots = snapshots.filter(bookmarked_at__gt=datetime.fromtimestamp(after))

    if sort:
        snapshots = snapshots.order_by(sort)

    # Export to requested format
    if json:
        output = snapshots.to_json(with_headers=with_headers)
    elif html:
        output = snapshots.to_html(with_headers=with_headers)
    elif csv:
        output = snapshots.to_csv(cols=csv.split(','), header=with_headers)
    else:
        from archivebox.misc.logging_util import printable_folders
        # Convert to dict for printable_folders
        folders = {s.output_dir: s for s in snapshots}
        output = printable_folders(folders, with_headers)

    print(output)
    return output
```

### Phase 8: Delete Folder Status Functions

File: `archivebox/misc/folders.py`

Delete lines 23-186 (all status checking functions):

```python
# DELETE these functions entirely:
# - _is_valid_snapshot()
# - _is_corrupt_snapshot()
# - get_indexed_folders()
# - get_archived_folders()
# - get_unarchived_folders()
# - get_present_folders()
# - get_valid_folders()
# - get_invalid_folders()
# - get_duplicate_folders()
# - get_orphaned_folders()
# - get_corrupted_folders()
# - get_unrecognized_folders()
```

Keep only `fix_invalid_folder_locations()` (used by archivebox init for one-time cleanup):

```python
"""
Folder utilities for ArchiveBox.

Note: This file only contains legacy cleanup utilities.
The DB is the single source of truth - use Snapshot.objects queries for all status checks.
"""

__package__ = 'archivebox.misc'

import os
import json
import shutil
from pathlib import Path
from typing import Tuple, List

from archivebox.config import DATA_DIR, CONSTANTS
from archivebox.misc.util import enforce_types


@enforce_types
def fix_invalid_folder_locations(out_dir: Path = DATA_DIR) -> Tuple[List[str], List[str]]:
    """
    Legacy cleanup: Move folders to their correct timestamp-named locations based on index.json.

    This is only used during 'archivebox init' for one-time cleanup of misnamed directories.
    After this runs once, 'archivebox update' handles all filesystem operations.
    """
    fixed = []
    cant_fix = []
    for entry in os.scandir(out_dir / CONSTANTS.ARCHIVE_DIR_NAME):
        if entry.is_dir(follow_symlinks=True):
            index_path = Path(entry.path) / 'index.json'
            if index_path.exists():
                try:
                    with open(index_path, 'r') as f:
                        data = json.load(f)
                    timestamp = data.get('timestamp')
                    url = data.get('url')
                except Exception:
                    continue

                if not timestamp:
                    continue

                if not entry.path.endswith(f'/{timestamp}'):
                    dest = out_dir / CONSTANTS.ARCHIVE_DIR_NAME / timestamp
                    if dest.exists():
                        cant_fix.append(entry.path)
                    else:
                        shutil.move(entry.path, str(dest))
                        fixed.append(str(dest))
    return fixed, cant_fix
```

---

## Testing Plan

1. **Test migration idempotency:**
   ```bash
   # Interrupt migration mid-way
   # Re-run - should resume seamlessly
   ```

2. **Test orphan import:**
   ```bash
   # Create orphaned directory manually
   # Run archivebox update
   # Verify imported and migrated
   ```

3. **Test deduplication:**
   ```bash
   # Create two snapshots with same url:timestamp
   # Run archivebox update
   # Verify merged
   ```

4. **Test timestamp uniqueness:**
   ```bash
   # Try to create snapshots with colliding timestamps
   # Verify auto-increment
   ```

5. **Test filtered update:**
   ```bash
   archivebox update --after 1234567890
   # Should only process DB, no filesystem scan
   ```

6. **Test continuous mode:**
   ```bash
   archivebox update --continuous
   # Should run in loop, prioritize newest entries
   ```

7. **Test DB-only commands:**
   ```bash
   archivebox search --status archived
   archivebox search example.com --filter-type substring
   archivebox remove example.com
   # All should query DB only, no filesystem scanning
   ```

---

## Implementation Checklist

- [x] Add all new methods to `Snapshot` model (Phase 1)
- [x] Update `output_dir` property (Phase 2)
- [x] Implement real `_fs_migrate_from_0_8_0_to_0_9_0()` (Phase 3)
- [x] Add `_cleanup_old_migration_dir()` helper (Phase 3)
- [x] Add timestamp uniqueness constraint (Phase 4)
- [x] Create database migration for constraint (Phase 4) - Created: `0032_alter_archiveresult_binary_and_more.py`
- [x] Rewrite `archivebox/cli/archivebox_update.py` (Phase 5)
- [x] Simplify `archivebox/cli/archivebox_init.py` (Phase 6)
- [x] Simplify `archivebox/cli/archivebox_search.py` (Phase 7)
- [x] Delete folder status functions from `archivebox/misc/folders.py` (Phase 8)
- [x] Update migration tests (test_migrations_08_to_09.py)
- [x] Update update command tests (tests/test_update.py)
- [ ] Run tests to verify implementation
- [ ] Test migration on real 0.8.x collection
- [ ] Test orphan import in production
- [ ] Test deduplication in production
- [ ] Test filtered vs full mode in production
- [ ] Test continuous mode in production
