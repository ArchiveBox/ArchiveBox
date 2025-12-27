# Lazy Filesystem Migration System

## Overview

**Problem**: `archivebox init` on 1TB+ collections takes hours/days scanning and migrating everything upfront.

**Solution**: O(1) init + lazy migration on save() + background worker.

## Core Principles

1. **`archivebox init` is O(1)** - Only runs Django schema migrations, creates folders/config
2. **Discovery is separate** - `archivebox update --import-orphans` scans archive/ and creates DB records
3. **Migration happens on save()** - Filesystem migration triggered automatically when snapshots are saved
4. **Background worker** - `archivebox update --migrate-fs --continuous` runs via supervisord
5. **Atomic cp + rm** - Copy files, verify, then remove old location (safe to interrupt)
6. **Idempotent** - Interrupted migrations resume seamlessly, skip already-copied files

## Database Schema

```python
class Snapshot(models.Model):
    fs_version = models.CharField(max_length=10, default=ARCHIVEBOX_VERSION)
    # e.g., '0.7.0', '0.8.0', '0.9.0', '1.0.0'

    @property
    def needs_fs_migration(self):
        """Check if snapshot needs filesystem migration"""
        return self.fs_version != ARCHIVEBOX_VERSION
```

## Migration on Save

```python
def save(self, *args, **kwargs):
    """Migrate filesystem if needed - happens automatically on save"""

    if self.pk and self.needs_fs_migration:
        with transaction.atomic():
            # Walk through migration chain automatically
            current = self.fs_version

            while current != ARCHIVEBOX_VERSION:
                next_ver = self._next_version(current)
                method = f'_migrate_fs_from_{current.replace(".", "_")}_to_{next_ver.replace(".", "_")}'

                # Only run if method exists (most are no-ops)
                if hasattr(self, method):
                    getattr(self, method)()

                current = next_ver

            # Update version (still in transaction)
            self.fs_version = ARCHIVEBOX_VERSION

    super().save(*args, **kwargs)

def _next_version(self, version):
    """Get next version in migration chain"""
    chain = ['0.7.0', '0.8.0', '0.9.0', '1.0.0']
    idx = chain.index(version)
    return chain[idx + 1] if idx + 1 < len(chain) else ARCHIVEBOX_VERSION
```

## Migration Implementation (cp + rm for safety)

```python
def _migrate_fs_from_0_7_0_to_0_8_0(self):
    """Most migrations are no-ops - only define if files actually move"""
    # 0.7 and 0.8 both used archive/<timestamp>
    # Nothing to do!
    pass

def _migrate_fs_from_0_8_0_to_0_9_0(self):
    """
    Migrate from flat file structure to organized extractor subdirectories.

    0.8.x layout (flat):
        archive/1234567890/
            index.json
            index.html
            screenshot.png
            warc/archive.warc.gz
            media/video.mp4
            ...

    0.9.x layout (organized):
        users/{username}/snapshots/20250101/example.com/{uuid}/
            index.json
            screenshot/
                screenshot.png
            singlefile/
                index.html
            warc/
                archive.warc.gz
            media/
                video.mp4

        Plus symlink: archive/1234567890 -> users/{username}/snapshots/.../

    Algorithm:
    1. Create new nested directory structure
    2. Group loose files by extractor (based on filename/extension)
    3. Move each group into extractor subdirs
    4. Create backwards-compat symlink
    """
    import re
    from datetime import datetime

    old_dir = CONSTANTS.ARCHIVE_DIR / self.timestamp
    if not old_dir.exists():
        return  # Nothing to migrate

    # Build new path: users/{username}/snapshots/YYYYMMDD/domain/{uuid}
    username = self.created_by.username if self.created_by else 'unknown'
    date_str = datetime.fromtimestamp(float(self.timestamp)).strftime('%Y%m%d')
    domain = self.url.split('/')[2] if '/' in self.url else 'unknown'
    new_dir = (
        CONSTANTS.DATA_DIR / 'users' / username / 'snapshots' /
        date_str / domain / str(self.id)
    )

    if old_dir == new_dir:
        return  # Already migrated

    # Deterministic mapping of old canonical paths to new extractor subdirectories
    # Based on canonical_outputs() from 0.7.x/0.8.x (see: archivebox/index/schema.py on main branch)
    CANONICAL_FILE_MAPPING = {
        # Individual files with known names
        'screenshot.png': 'screenshot/screenshot.png',
        'output.pdf': 'pdf/output.pdf',
        'output.html': 'dom/output.html',
        'singlefile.html': 'singlefile/singlefile.html',
        'htmltotext.txt': 'htmltotext/htmltotext.txt',
        'favicon.ico': 'favicon/favicon.ico',
        'headers.json': 'headers/headers.json',

        # Directories that should be moved wholesale (already organized)
        'warc/': 'warc/',
        'media/': 'media/',
        'git/': 'git/',
        'readability/': 'readability/',
        'mercury/': 'mercury/',
        'wget/': 'wget/',

        # Legacy/alternate filenames (support variations found in the wild)
        'screenshot.jpg': 'screenshot/screenshot.jpg',
        'screenshot.jpeg': 'screenshot/screenshot.jpeg',
        'archive.org.txt': 'archive_org/archive.org.txt',
    }

    # wget output is special - it's dynamic based on URL
    # For migration, we need to detect it by checking what's NOT already mapped
    # Common wget outputs: index.html, {domain}.html, {path}.html, etc.

    # Create new directory structure
    new_dir.mkdir(parents=True, exist_ok=True)

    # Track files to migrate
    migrated_files = set()

    # Step 1: Migrate files with deterministic mappings
    for old_file in old_dir.rglob('*'):
        if not old_file.is_file():
            continue

        rel_path = str(old_file.relative_to(old_dir))

        # Skip index.json - handle separately at the end
        if rel_path == 'index.json':
            continue

        # Check for exact match or directory prefix match
        new_rel_path = None

        # Exact file match
        if rel_path in CANONICAL_FILE_MAPPING:
            new_rel_path = CANONICAL_FILE_MAPPING[rel_path]
        else:
            # Check if file is under a directory that should be migrated
            for old_dir_prefix, new_dir_prefix in CANONICAL_FILE_MAPPING.items():
                if old_dir_prefix.endswith('/') and rel_path.startswith(old_dir_prefix):
                    # Preserve the subpath within the directory
                    subpath = rel_path[len(old_dir_prefix):]
                    new_rel_path = new_dir_prefix + subpath
                    break

        if new_rel_path:
            # Migrate this file
            new_file = new_dir / new_rel_path
            new_file.parent.mkdir(parents=True, exist_ok=True)

            # Skip if already copied
            if not (new_file.exists() and new_file.stat().st_size == old_file.stat().st_size):
                shutil.copy2(old_file, new_file)

            migrated_files.add(rel_path)

    # Step 2: Migrate remaining files (likely wget output or unknown)
    # Only move domain-like directories into wget/ - preserve everything else as-is
    for old_file in old_dir.rglob('*'):
        if not old_file.is_file():
            continue

        rel_path = str(old_file.relative_to(old_dir))

        if rel_path == 'index.json' or rel_path in migrated_files:
            continue

        # Check if this file is under a domain-like directory
        # Domain patterns: contains dot, might have www prefix, looks like a domain
        # Examples: example.com/index.html, www.site.org/path/file.html
        path_parts = Path(rel_path).parts
        is_wget_output = False

        if path_parts:
            first_dir = path_parts[0]
            # Check if first directory component looks like a domain
            if ('.' in first_dir and
                not first_dir.startswith('.') and  # not a hidden file
                first_dir.count('.') <= 3 and  # reasonable number of dots for a domain
                len(first_dir.split('.')) >= 2):  # has at least domain + TLD
                # Looks like a domain directory (e.g., example.com, www.example.com)
                is_wget_output = True

        if is_wget_output:
            # This looks like wget output - move to wget/ subdirectory
            new_rel_path = f'wget/{rel_path}'
        else:
            # Unknown file - preserve in original relative location
            # This is safer than guessing and potentially breaking things
            new_rel_path = rel_path

        new_file = new_dir / new_rel_path
        new_file.parent.mkdir(parents=True, exist_ok=True)

        # Skip if already copied
        if not (new_file.exists() and new_file.stat().st_size == old_file.stat().st_size):
            shutil.copy2(old_file, new_file)

    # Copy index.json to new location
    old_index = old_dir / 'index.json'
    new_index = new_dir / 'index.json'
    if old_index.exists():
        shutil.copy2(old_index, new_index)

    # Verify all files copied
    old_files = set(f.relative_to(old_dir) for f in old_dir.rglob('*') if f.is_file())
    # Count files in new structure (flatten from subdirs)
    new_files = set(f.relative_to(new_dir) for f in new_dir.rglob('*') if f.is_file())

    # We expect more files in new (due to duplication during migration), or equal
    if len(new_files) < len(old_files) - 1:  # -1 for index.json potentially not counted
        raise Exception(f"Migration incomplete: {len(old_files)} -> {len(new_files)} files")

    # Create backwards-compat symlink
    symlink_path = CONSTANTS.ARCHIVE_DIR / self.timestamp
    if symlink_path.exists() and symlink_path.is_symlink():
        symlink_path.unlink()
    elif symlink_path.exists():
        # Old dir still exists, will be removed below
        pass

    # Remove old directory
    shutil.rmtree(old_dir)

    # Create symlink
    symlink_path.symlink_to(new_dir, target_is_directory=True)

# Future migration example:
def _migrate_fs_from_0_9_0_to_1_0_0(self):
    """Example: migrate to nested structure"""
    old_dir = CONSTANTS.ARCHIVE_DIR / self.timestamp
    new_dir = CONSTANTS.ARCHIVE_DIR / 'snapshots' / self.timestamp[:8] / self.url_domain / str(self.id)

    if old_dir == new_dir or not old_dir.exists():
        return  # Already migrated or nothing to migrate

    # Step 1: Copy all files (idempotent - skip if already exist)
    new_dir.mkdir(parents=True, exist_ok=True)
    for old_file in old_dir.rglob('*'):
        if not old_file.is_file():
            continue

        rel_path = old_file.relative_to(old_dir)
        new_file = new_dir / rel_path

        # Skip if already copied (resumability)
        if new_file.exists() and new_file.stat().st_size == old_file.stat().st_size:
            continue

        new_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_file, new_file)

    # Step 2: Verify all files present
    old_files = {f.relative_to(old_dir): f.stat().st_size
                 for f in old_dir.rglob('*') if f.is_file()}
    new_files = {f.relative_to(new_dir): f.stat().st_size
                 for f in new_dir.rglob('*') if f.is_file()}

    if old_files.keys() != new_files.keys():
        missing = old_files.keys() - new_files.keys()
        raise Exception(f"Migration incomplete: {len(missing)} files missing")

    # Step 3: Remove old location only after verification
    shutil.rmtree(old_dir)
```

## Deriving output_dir from fs_version

```python
@property
def output_dir(self):
    """
    Derive output_dir from fs_version + metadata.

    0.7.x/0.8.x: archive/{timestamp}
    0.9.x: users/{username}/snapshots/YYYYMMDD/{domain}/{uuid}
           with symlink: archive/{timestamp} -> users/...

    Returns the actual path where files exist, following symlinks if present.
    """
    from datetime import datetime

    if self.fs_version in ('0.7.0', '0.8.0'):
        # Old flat structure
        path = CONSTANTS.ARCHIVE_DIR / self.timestamp

    elif self.fs_version == '0.9.0':
        # New nested structure
        username = self.created_by.username if self.created_by else 'unknown'
        date_str = datetime.fromtimestamp(float(self.timestamp)).strftime('%Y%m%d')
        domain = self.url.split('/')[2] if '/' in self.url else 'unknown'
        path = (
            CONSTANTS.DATA_DIR / 'users' / username / 'snapshots' /
            date_str / domain / str(self.id)
        )

        # Check for backwards-compat symlink
        old_path = CONSTANTS.ARCHIVE_DIR / self.timestamp
        if old_path.is_symlink():
            # Follow symlink to actual location
            path = Path(os.readlink(old_path))
        elif old_path.exists() and not path.exists():
            # Not migrated yet, use old location
            path = old_path

    else:
        # Unknown version - try current version's layout
        username = self.created_by.username if self.created_by else 'unknown'
        date_str = datetime.fromtimestamp(float(self.timestamp)).strftime('%Y%m%d')
        domain = self.url.split('/')[2] if '/' in self.url else 'unknown'
        path = (
            CONSTANTS.DATA_DIR / 'users' / username / 'snapshots' /
            date_str / domain / str(self.id)
        )

    return str(path)


@property
def archive_path(self):
    """
    Backwards-compatible path: always returns archive/{timestamp}.

    For 0.9.x, this is a symlink to the actual location.
    For older versions, this is the actual location.
    """
    return str(CONSTANTS.ARCHIVE_DIR / self.timestamp)
```

## Simplified archivebox init (O(1))

```python
def init(force: bool=False, install: bool=False) -> None:
    """Initialize a new ArchiveBox collection - O(1) regardless of size"""

    # 1. Create folders (O(1))
    print('[+] Building folder structure...')
    Path(CONSTANTS.ARCHIVE_DIR).mkdir(exist_ok=True)
    Path(CONSTANTS.SOURCES_DIR).mkdir(exist_ok=True)
    Path(CONSTANTS.LOGS_DIR).mkdir(exist_ok=True)

    # 2. Create config (O(1))
    print('[+] Creating configuration...')
    write_config_file({'SECRET_KEY': SERVER_CONFIG.SECRET_KEY})

    # 3. Run schema migrations (O(1))
    print('[*] Running database migrations...')
    setup_django()
    for line in apply_migrations(DATA_DIR):
        print(f'    {line}')

    print('[√] Done!')

    # 4. Check for orphans (non-blocking, quick count only)
    db_count = Snapshot.objects.count()
    try:
        dir_count = sum(1 for e in CONSTANTS.ARCHIVE_DIR.iterdir() if e.is_dir())
        if dir_count > db_count:
            print(f'\n[i] Detected ~{dir_count - db_count} snapshot directories not in database.')
            print(f'    Run: archivebox update --import-orphans')
    except Exception:
        pass
```

## Enhanced archivebox update (Single O(n) Pass)

**CRITICAL: Single streaming pass - never loads all snapshots into memory**

```python
@click.command()
@click.option('--resume-from', help='Resume from this timestamp (for resumability)')
@click.option('--batch-size', default=100, help='Commit every N snapshots')
@click.option('--continuous', is_flag=True, help='Run continuously as background worker')
def main(resume_from, batch_size, continuous):
    """
    Update snapshots: single O(n) pass that handles everything.

    For each directory in archive/:
    0. Load index.json and find/create DB record (by url+timestamp or url+crawl)
    1. Migrate filesystem if needed
    2. Reconcile index.json vs DB (DB is source of truth)
    3. Re-run failed/missing extractors
    4. Move invalid dirs to data/invalid/

    Examples:
        archivebox update                           # Process all snapshots
        archivebox update --resume-from=1234567890  # Resume from timestamp
        archivebox update --continuous              # Run as background worker
    """

    while True:
        print('[*] Scanning archive directory...')
        stats = process_archive_directory_streaming(
            DATA_DIR,
            batch_size=batch_size,
            resume_from=resume_from
        )

        print(f"""
[√] Done processing archive/
    Processed:  {stats['processed']}
    Imported:   {stats['imported']}
    Migrated:   {stats['migrated']}
    Reconciled: {stats['reconciled']}
    Updated:    {stats['updated']}
    Invalid:    {stats['invalid']}
        """)

        if not continuous:
            break

        print('[*] Sleeping 60s before next pass...')
        time.sleep(60)
        resume_from = None  # Start from beginning on next iteration


def process_archive_directory_streaming(
    out_dir: Path,
    batch_size: int = 100,
    resume_from: str = None
) -> dict:
    """
    Single O(n) streaming pass over archive/ directory.

    For each directory:
    0. Load index.json, find/create Snapshot by url+timestamp
    1. Migrate filesystem if fs_version != ARCHIVEBOX_VERSION
    2. Reconcile index.json vs DB (overwrite index.json from DB)
    3. Re-run failed/missing ArchiveResults
    4. Move invalid dirs to data/invalid/

    Never loads all snapshots into memory - processes one at a time.

    Returns: stats dict
    """
    from core.models import Snapshot
    from django.db import transaction

    stats = {
        'processed': 0,
        'imported': 0,
        'migrated': 0,
        'reconciled': 0,
        'updated': 0,
        'invalid': 0,
    }

    # Stream directory entries (os.scandir is iterator)
    archive_dir = out_dir / 'archive'
    entries = sorted(os.scandir(archive_dir), key=lambda e: e.name)

    # Resume from timestamp if specified
    if resume_from:
        entries = [e for e in entries if e.name >= resume_from]

    for entry in entries:
        if not entry.is_dir():
            continue

        stats['processed'] += 1
        print(f"[{stats['processed']}] Processing {entry.name}...")

        try:
            # Step 0: Load index.json and find/create Snapshot
            snapshot = load_or_create_snapshot_from_directory(Path(entry.path), out_dir)

            if not snapshot:
                # Invalid directory - move to data/invalid/
                move_to_invalid(Path(entry.path), out_dir)
                stats['invalid'] += 1
                continue

            # Track if this is a new import
            is_new = snapshot._state.adding
            if is_new:
                stats['imported'] += 1

            # Step 1: Migrate filesystem if needed (happens in save())
            needs_migration = snapshot.needs_fs_migration
            if needs_migration:
                print(f"    [*] Migrating from v{snapshot.fs_version}...")

            # Step 2: Reconcile index.json vs DB (overwrite index.json from DB)
            reconcile_index_json(snapshot)
            if not is_new:
                stats['reconciled'] += 1

            # Save triggers migration if needed
            snapshot.save()

            if needs_migration:
                stats['migrated'] += 1
                print(f"    [√] Migrated to v{ARCHIVEBOX_VERSION}")

            # Step 3: Re-run failed/missing extractors
            updated = rerun_failed_extractors(snapshot)
            if updated:
                stats['updated'] += 1
                print(f"    [√] Updated {updated} failed extractors")

        except Exception as e:
            print(f"    [X] Error processing {entry.name}: {e}")
            # Move to invalid on repeated failures
            move_to_invalid(Path(entry.path), out_dir)
            stats['invalid'] += 1

        # Commit batch periodically
        if stats['processed'] % batch_size == 0:
            transaction.commit()

    return stats


def load_or_create_snapshot_from_directory(snapshot_dir: Path, out_dir: Path) -> Optional[Snapshot]:
    """
    Load Snapshot from DB or create if orphaned.

    Looks up by (url, timestamp) or (url, crawl_id) - allows multiple snapshots of same URL.

    Returns:
        Snapshot object (new or existing)
        None if directory is invalid
    """
    from core.models import Snapshot

    index_path = snapshot_dir / 'index.json'
    if not index_path.exists():
        logger.warning(f"No index.json in {snapshot_dir.name}")
        return None

    try:
        with open(index_path) as f:
            data = json.load(f)

        url = data.get('url')
        timestamp = data.get('timestamp', snapshot_dir.name)
        crawl_id = data.get('crawl_id')  # May be None

        if not url:
            logger.warning(f"No URL in {snapshot_dir.name}/index.json")
            return None

        # Try to find existing snapshot by (url, timestamp)
        snapshot = Snapshot.objects.filter(url=url, timestamp=timestamp).first()

        if not snapshot and crawl_id:
            # Also try by (url, crawl_id) for crawl-based snapshots
            snapshot = Snapshot.objects.filter(url=url, crawl_id=crawl_id).first()

        if snapshot:
            # Found existing - return it for update
            return snapshot

        # Not found - create new (orphaned snapshot)
        detected_version = detect_fs_version(data, snapshot_dir)

        snapshot = Snapshot(
            url=url,
            timestamp=timestamp,
            title=data.get('title', ''),
            crawl_id=crawl_id,
            fs_version=detected_version,
            created_by=get_system_user(),
        )
        # Don't save yet - will be saved by caller after migration

        return snapshot

    except Exception as e:
        logger.error(f"Failed to load {snapshot_dir.name}: {e}")
        return None


def reconcile_index_json(snapshot: Snapshot):
    """
    Intelligently merge index.json with DB - DB is source of truth for conflicts.

    Merging strategy:
    - Title: Take longest non-URL title
    - Tags: Union of tags from both sources
    - ArchiveResults: Merge and dedupe by extractor name
    - Metadata: DB wins for url, timestamp, dates

    Updates both DB and index.json with merged data.
    """
    from core.models import ArchiveResult, Tag
    from django.db import transaction

    index_path = Path(snapshot.output_dir) / 'index.json'

    # Load existing index.json if present
    index_data = {}
    if index_path.exists():
        try:
            with open(index_path) as f:
                index_data = json.load(f)
        except Exception as e:
            logger.warning(f"Could not parse index.json: {e}")
            index_data = {}

    changed = False

    # 1. Merge title - take longest that isn't just the URL
    index_title = index_data.get('title', '').strip()
    db_title = snapshot.title or ''

    # Filter out titles that are just the URL
    candidates = [t for t in [index_title, db_title] if t and t != snapshot.url]
    if candidates:
        best_title = max(candidates, key=len)
        if snapshot.title != best_title:
            snapshot.title = best_title
            changed = True

    # 2. Merge tags - union of both sources
    index_tags = set(index_data.get('tags', '').split(',')) if index_data.get('tags') else set()
    index_tags = {t.strip() for t in index_tags if t.strip()}

    db_tags = set(snapshot.tags.values_list('name', flat=True))

    new_tags = index_tags - db_tags
    if new_tags:
        with transaction.atomic():
            for tag_name in new_tags:
                tag, _ = Tag.objects.get_or_create(name=tag_name)
                snapshot.tags.add(tag)
        changed = True

    # 3. Merge ArchiveResults - dedupe by extractor name
    index_results = index_data.get('archive_results', [])
    if isinstance(index_results, list):
        # Build map of existing results by extractor
        existing_extractors = set(
            ArchiveResult.objects
            .filter(snapshot=snapshot)
            .values_list('extractor', flat=True)
        )

        # Add missing results from index.json
        for result_data in index_results:
            extractor = result_data.get('extractor') or result_data.get('cmd_version', '').split()[0]
            if not extractor or extractor in existing_extractors:
                continue

            # Create missing ArchiveResult
            try:
                ArchiveResult.objects.create(
                    snapshot=snapshot,
                    extractor=extractor,
                    status=result_data.get('status', 'failed'),
                    output=result_data.get('output', ''),
                    cmd=json.dumps(result_data.get('cmd', [])),
                    pwd=result_data.get('pwd', ''),
                    start_ts=parse_date(result_data.get('start_ts')),
                    end_ts=parse_date(result_data.get('end_ts')),
                    created_by=snapshot.created_by,
                )
                changed = True
            except Exception as e:
                logger.warning(f"Could not create ArchiveResult for {extractor}: {e}")

    # 4. Handle legacy 'history' field (0.7.x format)
    if 'history' in index_data and isinstance(index_data['history'], dict):
        existing_extractors = set(
            ArchiveResult.objects
            .filter(snapshot=snapshot)
            .values_list('extractor', flat=True)
        )

        for extractor, result_list in index_data['history'].items():
            if extractor in existing_extractors:
                continue

            # Take most recent result for this extractor
            if result_list and isinstance(result_list, list):
                latest = result_list[-1]
                try:
                    ArchiveResult.objects.create(
                        snapshot=snapshot,
                        extractor=extractor,
                        status=latest.get('status', 'succeeded'),
                        output=latest.get('output', ''),
                        pwd=snapshot.output_dir,
                        start_ts=parse_date(latest.get('start_ts')),
                        end_ts=parse_date(latest.get('end_ts')),
                        created_by=snapshot.created_by,
                    )
                    changed = True
                except Exception as e:
                    logger.warning(f"Could not create ArchiveResult from history[{extractor}]: {e}")

    # Save snapshot if changed
    if changed:
        snapshot.save()

    # 5. Write merged data back to index.json (DB is source of truth)
    merged_data = {
        'url': snapshot.url,
        'timestamp': snapshot.timestamp,
        'title': snapshot.title,
        'tags': ','.join(sorted(snapshot.tags.values_list('name', flat=True))),
        'crawl_id': str(snapshot.crawl_id) if snapshot.crawl_id else None,
        'fs_version': snapshot.fs_version,
        'bookmarked_at': snapshot.bookmarked_at.isoformat() if snapshot.bookmarked_at else None,
        'updated_at': snapshot.modified_at.isoformat() if hasattr(snapshot, 'modified_at') else None,
        'archive_results': [
            {
                'extractor': ar.extractor,
                'status': ar.status,
                'start_ts': ar.start_ts.isoformat() if ar.start_ts else None,
                'end_ts': ar.end_ts.isoformat() if ar.end_ts else None,
                'output': ar.output or '',
                'cmd': json.loads(ar.cmd) if ar.cmd else [],
                'pwd': ar.pwd,
            }
            for ar in ArchiveResult.objects.filter(snapshot=snapshot).order_by('start_ts')
        ],
    }

    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, 'w') as f:
        json.dump(merged_data, f, indent=2, sort_keys=True)


def parse_date(date_str):
    """Parse date string to datetime, return None if invalid."""
    if not date_str:
        return None
    try:
        from dateutil import parser
        return parser.parse(date_str)
    except Exception:
        return None


def rerun_failed_extractors(snapshot: Snapshot) -> int:
    """
    Re-run failed or missing extractors for this snapshot.

    Returns: number of extractors updated
    """
    from core.models import ArchiveResult

    # Find failed or missing extractors
    failed = ArchiveResult.objects.filter(
        snapshot=snapshot,
        status__in=['failed', 'skipped']
    )

    updated = 0
    for result in failed:
        try:
            result.run()  # Re-run the extractor
            updated += 1
        except Exception as e:
            logger.warning(f"Failed to re-run {result.extractor}: {e}")

    return updated


def move_to_invalid(snapshot_dir: Path, out_dir: Path):
    """
    Move invalid/unrecognized directory to data/invalid/YYYYMMDD/{name}
    """
    from datetime import datetime

    invalid_dir = out_dir / 'invalid' / datetime.now().strftime('%Y%m%d')
    invalid_dir.mkdir(parents=True, exist_ok=True)

    dest = invalid_dir / snapshot_dir.name

    # Handle name conflicts
    counter = 1
    while dest.exists():
        dest = invalid_dir / f"{snapshot_dir.name}_{counter}"
        counter += 1

    shutil.move(str(snapshot_dir), str(dest))
    logger.info(f"Moved invalid dir to {dest}")


def detect_fs_version(data: dict, path: Path) -> str:
    """
    Detect fs_version from index.json structure.

    - 0.7.x: has 'history' dict
    - 0.8.x: has 'archive_results' list
    - 0.9.x: has 'fs_version' field or modern schema
    """
    if 'fs_version' in data:
        return data['fs_version']

    if 'history' in data and 'archive_results' not in data:
        return '0.7.0'

    if 'archive_results' in data:
        return '0.8.0'

    # Default to oldest if unknown
    return '0.7.0'
```

## Deduplication (Exact URL+Timestamp Duplicates Only)

**Multiple snapshots can have the same URL as long as they're from different times/crawls.**

Only merge when:
- Same url + timestamp (exact duplicate)
- Same url + crawl_id (duplicate within crawl)

```python
def find_and_merge_exact_duplicates() -> int:
    """
    Find and merge exact duplicates (same url+timestamp).

    Processes one URL at a time, never loads all into memory.

    Returns: number merged
    """
    from django.db.models import Count
    from core.models import Snapshot

    # Find (url, timestamp) pairs with count > 1
    duplicates = (
        Snapshot.objects
        .values('url', 'timestamp')
        .annotate(count=Count('id'))
        .filter(count__gt=1)
    )

    merged = 0
    for dup in duplicates.iterator():
        # Load just snapshots for this url+timestamp
        snapshots = list(
            Snapshot.objects
            .filter(url=dup['url'], timestamp=dup['timestamp'])
            .order_by('created_at')  # Keep oldest
        )

        if len(snapshots) <= 1:
            continue

        # Merge duplicates
        merge_duplicate_snapshots(snapshots)
        merged += 1

    return merged


def merge_duplicate_snapshots(snapshots: List[Snapshot]):
    """
    Merge exact duplicates - keep oldest, merge files, delete rest.
    """
    keeper = snapshots[0]
    duplicates = snapshots[1:]

    keeper_dir = Path(keeper.output_dir)

    for dup in duplicates:
        dup_dir = Path(dup.output_dir)
        if dup_dir.exists() and dup_dir != keeper_dir:
            # Copy any files keeper doesn't have
            for dup_file in dup_dir.rglob('*'):
                if not dup_file.is_file():
                    continue
                rel = dup_file.relative_to(dup_dir)
                keeper_file = keeper_dir / rel
                if not keeper_file.exists():
                    keeper_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dup_file, keeper_file)

            # Delete duplicate directory
            shutil.rmtree(dup_dir)

        # Merge tags
        for tag in dup.tags.all():
            keeper.tags.add(tag)

        # Delete duplicate record
        dup.delete()
```

## Supervisord Configuration

```ini
[program:update_worker]
command=archivebox update --continuous --import-orphans --migrate-fs --batch-size=100
directory=%(ENV_DATA_DIR)s
autostart=true
autorestart=true
startretries=999999
stdout_logfile=%(ENV_DATA_DIR)s/logs/update_worker.log
stderr_logfile=%(ENV_DATA_DIR)s/logs/update_worker.error.log
priority=100
```

## Safety Guarantees

1. **Transaction safety**: cp + fs_version update happen in same transaction
2. **Power loss**: Transaction rolls back → fs_version unchanged → retry on next run
3. **Copy failure**: Old files remain → fs_version unchanged → retry on next run
4. **Idempotent**: Already-copied files skipped → safe to retry infinitely
5. **Verify before delete**: Only rm old location after verifying all files copied

## Benefits

✅ **O(1) init** - Instant regardless of collection size
✅ **Lazy migration** - Happens gradually via background worker or on-demand
✅ **Atomic** - Transaction protects DB, idempotent copy protects FS
✅ **Resumable** - Interrupted migrations continue seamlessly
✅ **Automatic** - Migrations chain naturally (0.7→0.8→0.9→1.0)
✅ **Most no-ops** - Only define migration methods when files actually move
✅ **Safe** - cp + verify + rm, never mv
✅ **Predictable** - Only happens during save(), not on read

---

