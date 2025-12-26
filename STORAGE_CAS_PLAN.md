# Content-Addressable Storage (CAS) with Symlink Farm Architecture

## Table of Contents
- [Overview](#overview)
- [Architecture Design](#architecture-design)
- [Database Models](#database-models)
- [Storage Backends](#storage-backends)
- [Symlink Farm Views](#symlink-farm-views)
- [Automatic Synchronization](#automatic-synchronization)
- [Migration Strategy](#migration-strategy)
- [Verification and Repair](#verification-and-repair)
- [Configuration](#configuration)
- [Workflow Examples](#workflow-examples)
- [Benefits](#benefits)

## Overview

### Problem Statement
ArchiveBox currently stores files in a timestamp-based structure:
```
/data/archive/{timestamp}/{extractor}/filename.ext
```

This leads to:
- **Massive duplication**: `jquery.min.js` stored 1000x across different snapshots
- **No S3 support**: Direct filesystem coupling
- **Inflexible organization**: Hard to browse by domain, date, or user

### Solution: Content-Addressable Storage + Symlink Farm

**Core Concept:**
1. **Store files once** in content-addressable storage (CAS) by hash
2. **Create symlink farms** in multiple human-readable views
3. **Database as source of truth** with automatic sync
4. **Support S3 and local storage** via django-storages

**Storage Layout:**
```
/data/
├── cas/                                    # Content-addressable storage (deduplicated)
│   └── sha256/
│       └── ab/
│           └── cd/
│               └── abcdef123...           # Actual file (stored once)
│
├── archive/                                # Human-browseable views (all symlinks)
│   ├── by_domain/
│   │   └── example.com/
│   │       └── 20241225/
│   │           └── 019b54ee-28d9-72dc/
│   │               ├── wget/
│   │               │   └── index.html -> ../../../../../cas/sha256/ab/cd/abcdef...
│   │               └── singlefile/
│   │                   └── page.html -> ../../../../../cas/sha256/ef/12/ef1234...
│   │
│   ├── by_date/
│   │   └── 20241225/
│   │       └── example.com/
│   │           └── 019b54ee-28d9-72dc/
│   │               └── wget/
│   │                   └── index.html -> ../../../../../../cas/sha256/ab/cd/abcdef...
│   │
│   ├── by_user/
│   │   └── squash/
│   │       └── 20241225/
│   │           └── example.com/
│   │               └── 019b54ee-28d9-72dc/
│   │
│   └── by_timestamp/                      # Legacy compatibility
│       └── 1735142400.123/
│           └── wget/
│               └── index.html -> ../../../../cas/sha256/ab/cd/abcdef...
```

## Architecture Design

### Core Principles

1. **Database = Source of Truth**: The `SnapshotFile` model is authoritative
2. **Symlinks = Materialized Views**: Auto-generated from DB, disposable
3. **Atomic Updates**: Symlinks created/deleted with DB transactions
4. **Idempotent**: Operations can be safely retried
5. **Self-Healing**: Automatic detection and repair of drift
6. **Content-Addressable**: Files deduplicated by SHA-256 hash
7. **Storage Agnostic**: Works with local filesystem, S3, Azure, etc.

### Space Overhead Analysis

Symlinks are incredibly cheap:
```
Typical symlink size:
- ext4/XFS: ~60-100 bytes
- ZFS: ~120 bytes
- btrfs: ~80 bytes

Example calculation:
100,000 files × 4 views = 400,000 symlinks
400,000 symlinks × 100 bytes = 40 MB

Space saved by deduplication:
- Average 30% duplicate content across archives
- 100GB archive → saves ~30GB
- Symlink overhead: 0.04GB (0.13% of savings!)

Verdict: Symlinks are FREE compared to deduplication savings
```

## Database Models

### Blob Model

```python
# archivebox/core/models.py

class Blob(models.Model):
    """
    Immutable content-addressed blob.
    Stored as: /cas/{hash_algorithm}/{ab}/{cd}/{full_hash}
    """

    # Content identification
    hash_algorithm = models.CharField(max_length=16, default='sha256', db_index=True)
    hash = models.CharField(max_length=128, db_index=True)
    size = models.BigIntegerField()

    # Storage location
    storage_backend = models.CharField(
        max_length=32,
        default='local',
        choices=[
            ('local', 'Local Filesystem'),
            ('s3', 'S3'),
            ('azure', 'Azure Blob Storage'),
            ('gcs', 'Google Cloud Storage'),
        ],
        db_index=True,
    )

    # Metadata
    mime_type = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # Reference counting (for garbage collection)
    ref_count = models.IntegerField(default=0, db_index=True)

    class Meta:
        unique_together = [('hash_algorithm', 'hash', 'storage_backend')]
        indexes = [
            models.Index(fields=['hash_algorithm', 'hash']),
            models.Index(fields=['ref_count']),
            models.Index(fields=['storage_backend', 'created_at']),
        ]
        constraints = [
            # Ensure ref_count is never negative
            models.CheckConstraint(
                check=models.Q(ref_count__gte=0),
                name='blob_ref_count_positive'
            ),
        ]

    def __str__(self):
        return f"Blob({self.hash[:16]}..., refs={self.ref_count})"

    @property
    def storage_path(self) -> str:
        """Content-addressed path: sha256/ab/cd/abcdef123..."""
        h = self.hash
        return f"{self.hash_algorithm}/{h[:2]}/{h[2:4]}/{h}"

    def get_file_url(self):
        """Get URL to access this blob"""
        from django.core.files.storage import default_storage
        return default_storage.url(self.storage_path)


class SnapshotFile(models.Model):
    """
    Links a Snapshot to its files (many-to-many through Blob).
    Preserves original path information for backwards compatibility.
    """

    snapshot = models.ForeignKey(
        Snapshot,
        on_delete=models.CASCADE,
        related_name='files'
    )
    blob = models.ForeignKey(
        Blob,
        on_delete=models.PROTECT  # PROTECT: can't delete blob while referenced
    )

    # Original path information
    extractor = models.CharField(max_length=32)  # 'wget', 'singlefile', etc.
    relative_path = models.CharField(max_length=512)  # 'output.html', 'warc/example.warc.gz'

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        unique_together = [('snapshot', 'extractor', 'relative_path')]
        indexes = [
            models.Index(fields=['snapshot', 'extractor']),
            models.Index(fields=['blob']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.snapshot.id}/{self.extractor}/{self.relative_path}"

    @property
    def logical_path(self) -> Path:
        """Virtual path as it would appear in old structure"""
        return Path(self.snapshot.output_dir) / self.extractor / self.relative_path

    def save(self, *args, **kwargs):
        """Override save to ensure paths are normalized"""
        # Normalize path (no leading slash, use forward slashes)
        self.relative_path = self.relative_path.lstrip('/').replace('\\', '/')
        super().save(*args, **kwargs)
```

### Updated Snapshot Model

```python
class Snapshot(ModelWithOutputDir, ...):
    # ... existing fields ...

    @property
    def output_dir(self) -> Path:
        """
        Returns the primary view directory for browsing.
        Falls back to legacy if needed.
        """
        # Try by_timestamp view first (best compatibility)
        by_timestamp = CONSTANTS.ARCHIVE_DIR / 'by_timestamp' / self.timestamp
        if by_timestamp.exists():
            return by_timestamp

        # Fall back to legacy location (pre-CAS archives)
        legacy = CONSTANTS.ARCHIVE_DIR / self.timestamp
        if legacy.exists():
            return legacy

        # Default to by_timestamp for new snapshots
        return by_timestamp

    def get_output_dir(self, view: str = 'by_timestamp') -> Path:
        """Get output directory for a specific view"""
        from storage.views import ViewManager
        from urllib.parse import urlparse

        if view not in ViewManager.VIEWS:
            raise ValueError(f"Unknown view: {view}")

        if view == 'by_domain':
            domain = urlparse(self.url).netloc or 'unknown'
            date = self.created_at.strftime('%Y%m%d')
            return CONSTANTS.ARCHIVE_DIR / 'by_domain' / domain / date / str(self.id)

        elif view == 'by_date':
            domain = urlparse(self.url).netloc or 'unknown'
            date = self.created_at.strftime('%Y%m%d')
            return CONSTANTS.ARCHIVE_DIR / 'by_date' / date / domain / str(self.id)

        elif view == 'by_user':
            domain = urlparse(self.url).netloc or 'unknown'
            date = self.created_at.strftime('%Y%m%d')
            user = self.created_by.username
            return CONSTANTS.ARCHIVE_DIR / 'by_user' / user / date / domain / str(self.id)

        elif view == 'by_timestamp':
            return CONSTANTS.ARCHIVE_DIR / 'by_timestamp' / self.timestamp

        return self.output_dir
```

### Updated ArchiveResult Model

```python
class ArchiveResult(models.Model):
    # ... existing fields ...

    # Note: output_dir field is removed (was deprecated)
    # Keep: output (relative path to primary output file)

    @property
    def output_files(self):
        """Get all files for this extractor"""
        return self.snapshot.files.filter(extractor=self.extractor)

    @property
    def primary_output_file(self):
        """Get the primary output file (e.g., 'output.html')"""
        if self.output:
            return self.snapshot.files.filter(
                extractor=self.extractor,
                relative_path=self.output
            ).first()
        return None
```

## Storage Backends

### Django Storage Configuration

```python
# settings.py or archivebox/config/settings.py

# For local development/testing
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {
            "location": "/data/cas",
            "base_url": "/cas/",
        },
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# For production with S3
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": "archivebox-blobs",
            "region_name": "us-east-1",
            "default_acl": "private",
            "object_parameters": {
                "StorageClass": "INTELLIGENT_TIERING",  # Auto-optimize storage costs
            },
        },
    },
}
```

### Blob Manager

```python
# archivebox/storage/ingest.py

import hashlib
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.db import transaction
from pathlib import Path
import os

class BlobManager:
    """Manages content-addressed blob storage with deduplication"""

    @staticmethod
    def hash_file(file_path: Path, algorithm='sha256') -> str:
        """Calculate content hash of a file"""
        hasher = hashlib.new(algorithm)
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def ingest_file(
        file_path: Path,
        snapshot,
        extractor: str,
        relative_path: str,
        mime_type: str = '',
        create_views: bool = True,
    ) -> SnapshotFile:
        """
        Ingest a file into blob storage with deduplication.

        Args:
            file_path: Path to the file to ingest
            snapshot: Snapshot this file belongs to
            extractor: Extractor name (wget, singlefile, etc.)
            relative_path: Relative path within extractor dir
            mime_type: MIME type of the file
            create_views: Whether to create symlink views

        Returns:
            SnapshotFile reference
        """
        from storage.views import ViewManager

        # Calculate hash
        file_hash = BlobManager.hash_file(file_path)
        file_size = file_path.stat().st_size

        with transaction.atomic():
            # Check if blob already exists (deduplication!)
            blob, created = Blob.objects.get_or_create(
                hash_algorithm='sha256',
                hash=file_hash,
                storage_backend='local',
                defaults={
                    'size': file_size,
                    'mime_type': mime_type,
                }
            )

            if created:
                # New blob - store in CAS
                cas_path = ViewManager.get_cas_path(blob)
                cas_path.parent.mkdir(parents=True, exist_ok=True)

                # Use hardlink if possible (instant), copy if not
                try:
                    os.link(file_path, cas_path)
                except OSError:
                    import shutil
                    shutil.copy2(file_path, cas_path)

                print(f"✓ Stored new blob: {file_hash[:16]}... ({file_size:,} bytes)")
            else:
                print(f"✓ Deduplicated: {file_hash[:16]}... (saved {file_size:,} bytes)")

            # Increment reference count
            blob.ref_count += 1
            blob.save(update_fields=['ref_count'])

            # Create snapshot file reference
            snapshot_file, _ = SnapshotFile.objects.get_or_create(
                snapshot=snapshot,
                extractor=extractor,
                relative_path=relative_path,
                defaults={'blob': blob}
            )

            # Create symlink views (signal will also do this, but we can force it here)
            if create_views:
                views = ViewManager.create_symlinks(snapshot_file)
                print(f"  Created {len(views)} view symlinks")

            return snapshot_file

    @staticmethod
    def ingest_directory(
        dir_path: Path,
        snapshot,
        extractor: str
    ) -> list[SnapshotFile]:
        """Ingest all files from a directory"""
        import mimetypes

        snapshot_files = []

        for file_path in dir_path.rglob('*'):
            if file_path.is_file():
                relative_path = str(file_path.relative_to(dir_path))
                mime_type, _ = mimetypes.guess_type(str(file_path))

                snapshot_file = BlobManager.ingest_file(
                    file_path,
                    snapshot,
                    extractor,
                    relative_path,
                    mime_type or ''
                )
                snapshot_files.append(snapshot_file)

        return snapshot_files
```

## Symlink Farm Views

### View Classes

```python
# archivebox/storage/views.py

from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
import os
import logging

logger = logging.getLogger(__name__)


class SnapshotView(Protocol):
    """Protocol for generating browseable views of snapshots"""

    def get_view_path(self, snapshot_file: SnapshotFile) -> Path:
        """Get the human-readable path for this file in this view"""
        ...


class ByDomainView:
    """View: /archive/by_domain/{domain}/{YYYYMMDD}/{snapshot_id}/{extractor}/{filename}"""

    def get_view_path(self, snapshot_file: SnapshotFile) -> Path:
        snapshot = snapshot_file.snapshot
        domain = urlparse(snapshot.url).netloc or 'unknown'
        date = snapshot.created_at.strftime('%Y%m%d')

        return (
            CONSTANTS.ARCHIVE_DIR / 'by_domain' / domain / date /
            str(snapshot.id) / snapshot_file.extractor / snapshot_file.relative_path
        )


class ByDateView:
    """View: /archive/by_date/{YYYYMMDD}/{domain}/{snapshot_id}/{extractor}/{filename}"""

    def get_view_path(self, snapshot_file: SnapshotFile) -> Path:
        snapshot = snapshot_file.snapshot
        domain = urlparse(snapshot.url).netloc or 'unknown'
        date = snapshot.created_at.strftime('%Y%m%d')

        return (
            CONSTANTS.ARCHIVE_DIR / 'by_date' / date / domain /
            str(snapshot.id) / snapshot_file.extractor / snapshot_file.relative_path
        )


class ByUserView:
    """View: /archive/by_user/{username}/{YYYYMMDD}/{domain}/{snapshot_id}/{extractor}/{filename}"""

    def get_view_path(self, snapshot_file: SnapshotFile) -> Path:
        snapshot = snapshot_file.snapshot
        user = snapshot.created_by.username
        domain = urlparse(snapshot.url).netloc or 'unknown'
        date = snapshot.created_at.strftime('%Y%m%d')

        return (
            CONSTANTS.ARCHIVE_DIR / 'by_user' / user / date / domain /
            str(snapshot.id) / snapshot_file.extractor / snapshot_file.relative_path
        )


class LegacyTimestampView:
    """View: /archive/by_timestamp/{timestamp}/{extractor}/{filename}"""

    def get_view_path(self, snapshot_file: SnapshotFile) -> Path:
        snapshot = snapshot_file.snapshot

        return (
            CONSTANTS.ARCHIVE_DIR / 'by_timestamp' / snapshot.timestamp /
            snapshot_file.extractor / snapshot_file.relative_path
        )


class ViewManager:
    """Manages symlink farm views"""

    VIEWS = {
        'by_domain': ByDomainView(),
        'by_date': ByDateView(),
        'by_user': ByUserView(),
        'by_timestamp': LegacyTimestampView(),
    }

    @staticmethod
    def get_cas_path(blob: Blob) -> Path:
        """Get the CAS storage path for a blob"""
        h = blob.hash
        return (
            CONSTANTS.DATA_DIR / 'cas' / blob.hash_algorithm /
            h[:2] / h[2:4] / h
        )

    @staticmethod
    def create_symlinks(snapshot_file: SnapshotFile, views: list[str] = None) -> dict[str, Path]:
        """
        Create symlinks for all views of a file.
        If any operation fails, all are rolled back.
        """
        from config.common import STORAGE_CONFIG

        if views is None:
            views = STORAGE_CONFIG.ENABLED_VIEWS

        cas_path = ViewManager.get_cas_path(snapshot_file.blob)

        # Verify CAS file exists before creating symlinks
        if not cas_path.exists():
            raise FileNotFoundError(f"CAS file missing: {cas_path}")

        created = {}
        cleanup_on_error = []

        try:
            for view_name in views:
                if view_name not in ViewManager.VIEWS:
                    continue

                view = ViewManager.VIEWS[view_name]
                view_path = view.get_view_path(snapshot_file)

                # Create parent directory
                view_path.parent.mkdir(parents=True, exist_ok=True)

                # Create relative symlink (more portable)
                rel_target = os.path.relpath(cas_path, view_path.parent)

                # Remove existing symlink/file if present
                if view_path.exists() or view_path.is_symlink():
                    view_path.unlink()

                # Create symlink
                view_path.symlink_to(rel_target)
                created[view_name] = view_path
                cleanup_on_error.append(view_path)

            return created

        except Exception as e:
            # Rollback: Remove partially created symlinks
            for path in cleanup_on_error:
                try:
                    if path.exists() or path.is_symlink():
                        path.unlink()
                except Exception as cleanup_error:
                    logger.error(f"Failed to cleanup {path}: {cleanup_error}")

            raise Exception(f"Failed to create symlinks: {e}")

    @staticmethod
    def create_symlinks_idempotent(snapshot_file: SnapshotFile, views: list[str] = None):
        """
        Idempotent version - safe to call multiple times.
        Returns dict of created symlinks, or empty dict if already correct.
        """
        from config.common import STORAGE_CONFIG

        if views is None:
            views = STORAGE_CONFIG.ENABLED_VIEWS

        cas_path = ViewManager.get_cas_path(snapshot_file.blob)
        needs_update = False

        # Check if all symlinks exist and point to correct target
        for view_name in views:
            if view_name not in ViewManager.VIEWS:
                continue

            view = ViewManager.VIEWS[view_name]
            view_path = view.get_view_path(snapshot_file)

            if not view_path.is_symlink():
                needs_update = True
                break

            # Check if symlink points to correct target
            try:
                current_target = view_path.resolve()
                if current_target != cas_path:
                    needs_update = True
                    break
            except Exception:
                needs_update = True
                break

        if needs_update:
            return ViewManager.create_symlinks(snapshot_file, views)

        return {}  # Already correct

    @staticmethod
    def cleanup_symlinks(snapshot_file: SnapshotFile):
        """Remove all symlinks for a file"""
        from config.common import STORAGE_CONFIG

        for view_name in STORAGE_CONFIG.ENABLED_VIEWS:
            if view_name not in ViewManager.VIEWS:
                continue

            view = ViewManager.VIEWS[view_name]
            view_path = view.get_view_path(snapshot_file)

            if view_path.exists() or view_path.is_symlink():
                view_path.unlink()
                logger.info(f"Removed symlink: {view_path}")
```

## Automatic Synchronization

### Django Signals for Sync

```python
# archivebox/storage/signals.py

from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver
from django.db import transaction
from core.models import SnapshotFile, Blob
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=SnapshotFile)
def sync_symlinks_on_save(sender, instance, created, **kwargs):
    """
    Automatically create/update symlinks when SnapshotFile is saved.
    Runs AFTER transaction commit to ensure DB consistency.
    """
    from config.common import STORAGE_CONFIG

    if not STORAGE_CONFIG.AUTO_SYNC_SYMLINKS:
        return

    if created:
        # New file - create all symlinks
        try:
            from storage.views import ViewManager
            views = ViewManager.create_symlinks(instance)
            logger.info(f"Created {len(views)} symlinks for {instance.relative_path}")
        except Exception as e:
            logger.error(f"Failed to create symlinks for {instance.id}: {e}")
            # Don't fail the transaction - can be repaired later


@receiver(pre_delete, sender=SnapshotFile)
def sync_symlinks_on_delete(sender, instance, **kwargs):
    """
    Remove symlinks when SnapshotFile is deleted.
    Runs BEFORE deletion so we still have the data.
    """
    try:
        from storage.views import ViewManager
        ViewManager.cleanup_symlinks(instance)
        logger.info(f"Removed symlinks for {instance.relative_path}")
    except Exception as e:
        logger.error(f"Failed to remove symlinks for {instance.id}: {e}")


@receiver(post_delete, sender=SnapshotFile)
def cleanup_unreferenced_blob(sender, instance, **kwargs):
    """
    Decrement blob reference count and cleanup if no longer referenced.
    """
    try:
        blob = instance.blob

        # Atomic decrement
        from django.db.models import F
        Blob.objects.filter(pk=blob.pk).update(ref_count=F('ref_count') - 1)

        # Reload to get updated count
        blob.refresh_from_db()

        # Garbage collect if no more references
        if blob.ref_count <= 0:
            from storage.views import ViewManager
            cas_path = ViewManager.get_cas_path(blob)

            if cas_path.exists():
                cas_path.unlink()
                logger.info(f"Garbage collected blob {blob.hash[:16]}...")

            blob.delete()

    except Exception as e:
        logger.error(f"Failed to cleanup blob: {e}")
```

### App Configuration

```python
# archivebox/storage/apps.py

from django.apps import AppConfig

class StorageConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'storage'

    def ready(self):
        import storage.signals  # Register signal handlers
```

## Migration Strategy

### Migration Command

```python
# archivebox/core/management/commands/migrate_to_cas.py

from django.core.management.base import BaseCommand
from django.db.models import Q
from core.models import Snapshot
from storage.ingest import BlobManager
from storage.views import ViewManager
from pathlib import Path
import shutil

class Command(BaseCommand):
    help = 'Migrate existing archives to content-addressable storage'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
        parser.add_argument('--views', nargs='+', default=['by_timestamp', 'by_domain', 'by_date'])
        parser.add_argument('--cleanup-legacy', action='store_true', help='Delete old files after migration')
        parser.add_argument('--batch-size', type=int, default=100)

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        views = options['views']
        cleanup = options['cleanup_legacy']
        batch_size = options['batch_size']

        snapshots = Snapshot.objects.all().order_by('created_at')
        total = snapshots.count()

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No changes will be made'))

        self.stdout.write(f"Found {total} snapshots to migrate")

        total_files = 0
        total_saved = 0
        total_bytes = 0
        error_count = 0

        for i, snapshot in enumerate(snapshots, 1):
            self.stdout.write(f"\n[{i}/{total}] Processing {snapshot.url[:60]}...")

            legacy_dir = CONSTANTS.ARCHIVE_DIR / snapshot.timestamp

            if not legacy_dir.exists():
                self.stdout.write(f"  Skipping (no legacy dir)")
                continue

            # Process each extractor directory
            for extractor_dir in legacy_dir.iterdir():
                if not extractor_dir.is_dir():
                    continue

                extractor = extractor_dir.name
                self.stdout.write(f"  Processing extractor: {extractor}")

                if dry_run:
                    file_count = sum(1 for _ in extractor_dir.rglob('*') if _.is_file())
                    self.stdout.write(f"    Would ingest {file_count} files")
                    continue

                # Track blobs before ingestion
                blobs_before = Blob.objects.count()

                try:
                    # Ingest all files from this extractor
                    ingested = BlobManager.ingest_directory(
                        extractor_dir,
                        snapshot,
                        extractor
                    )

                    total_files += len(ingested)

                    # Calculate deduplication savings
                    blobs_after = Blob.objects.count()
                    new_blobs = blobs_after - blobs_before
                    dedup_count = len(ingested) - new_blobs

                    if dedup_count > 0:
                        dedup_bytes = sum(f.blob.size for f in ingested[-dedup_count:])
                        total_saved += dedup_bytes
                        self.stdout.write(
                            f"    ✓ Ingested {len(ingested)} files "
                            f"({new_blobs} new, {dedup_count} deduplicated, "
                            f"saved {dedup_bytes / 1024 / 1024:.1f} MB)"
                        )
                    else:
                        total_bytes_added = sum(f.blob.size for f in ingested)
                        total_bytes += total_bytes_added
                        self.stdout.write(
                            f"    ✓ Ingested {len(ingested)} files "
                            f"({total_bytes_added / 1024 / 1024:.1f} MB)"
                        )

                except Exception as e:
                    error_count += 1
                    self.stdout.write(self.style.ERROR(f"    ✗ Error: {e}"))
                    continue

            # Cleanup legacy files
            if cleanup and not dry_run:
                try:
                    shutil.rmtree(legacy_dir)
                    self.stdout.write(f"  Cleaned up legacy dir: {legacy_dir}")
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Failed to cleanup: {e}"))

            # Progress update
            if i % 10 == 0:
                self.stdout.write(
                    f"\nProgress: {i}/{total} | "
                    f"Files: {total_files:,} | "
                    f"Saved: {total_saved / 1024 / 1024:.1f} MB | "
                    f"Errors: {error_count}"
                )

        # Final summary
        self.stdout.write("\n" + "="*80)
        self.stdout.write(self.style.SUCCESS("Migration Complete!"))
        self.stdout.write(f"  Snapshots processed: {total}")
        self.stdout.write(f"  Files ingested: {total_files:,}")
        self.stdout.write(f"  Space saved by deduplication: {total_saved / 1024 / 1024:.1f} MB")
        self.stdout.write(f"  Errors: {error_count}")
        self.stdout.write(f"  Symlink views created: {', '.join(views)}")
```

### Rebuild Views Command

```python
# archivebox/core/management/commands/rebuild_views.py

from django.core.management.base import BaseCommand
from core.models import SnapshotFile
from storage.views import ViewManager
import shutil

class Command(BaseCommand):
    help = 'Rebuild symlink farm views from database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--views',
            nargs='+',
            default=['by_timestamp', 'by_domain', 'by_date'],
            help='Which views to rebuild'
        )
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Remove old symlinks before rebuilding'
        )

    def handle(self, *args, **options):
        views = options['views']
        clean = options['clean']

        # Clean old views
        if clean:
            self.stdout.write("Cleaning old views...")
            for view_name in views:
                view_dir = CONSTANTS.ARCHIVE_DIR / view_name
                if view_dir.exists():
                    shutil.rmtree(view_dir)
                    self.stdout.write(f"  Removed {view_dir}")

        # Rebuild all symlinks
        total_symlinks = 0
        total_files = SnapshotFile.objects.count()

        self.stdout.write(f"Rebuilding symlinks for {total_files:,} files...")

        for i, snapshot_file in enumerate(
            SnapshotFile.objects.select_related('snapshot', 'blob'),
            1
        ):
            try:
                created = ViewManager.create_symlinks(snapshot_file, views=views)
                total_symlinks += len(created)
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"Failed to create symlinks for {snapshot_file}: {e}"
                ))

            if i % 1000 == 0:
                self.stdout.write(f"  Created {total_symlinks:,} symlinks...")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Rebuilt {total_symlinks:,} symlinks across {len(views)} views"
            )
        )
```

## Verification and Repair

### Storage Verification Command

```python
# archivebox/core/management/commands/verify_storage.py

from django.core.management.base import BaseCommand
from core.models import SnapshotFile, Blob
from storage.views import ViewManager
from pathlib import Path

class Command(BaseCommand):
    help = 'Verify storage consistency between DB and filesystem'

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true', help='Fix issues found')
        parser.add_argument('--vacuum', action='store_true', help='Remove orphaned symlinks')

    def handle(self, *args, **options):
        fix = options['fix']
        vacuum = options['vacuum']

        issues = {
            'missing_cas_files': [],
            'missing_symlinks': [],
            'incorrect_symlinks': [],
            'orphaned_symlinks': [],
            'orphaned_blobs': [],
        }

        self.stdout.write("Checking database → filesystem consistency...")

        # Check 1: Verify all blobs exist in CAS
        self.stdout.write("\n1. Verifying CAS files...")
        for blob in Blob.objects.all():
            cas_path = ViewManager.get_cas_path(blob)
            if not cas_path.exists():
                issues['missing_cas_files'].append(blob)
                self.stdout.write(self.style.ERROR(
                    f"✗ Missing CAS file: {cas_path} (blob {blob.hash[:16]}...)"
                ))

        # Check 2: Verify all SnapshotFiles have correct symlinks
        self.stdout.write("\n2. Verifying symlinks...")
        total_files = SnapshotFile.objects.count()

        for i, sf in enumerate(SnapshotFile.objects.select_related('blob'), 1):
            if i % 100 == 0:
                self.stdout.write(f"  Checked {i}/{total_files} files...")

            cas_path = ViewManager.get_cas_path(sf.blob)

            for view_name in STORAGE_CONFIG.ENABLED_VIEWS:
                view = ViewManager.VIEWS[view_name]
                view_path = view.get_view_path(sf)

                if not view_path.exists() and not view_path.is_symlink():
                    issues['missing_symlinks'].append((sf, view_name, view_path))

                    if fix:
                        try:
                            ViewManager.create_symlinks_idempotent(sf, [view_name])
                            self.stdout.write(self.style.SUCCESS(
                                f"✓ Created missing symlink: {view_path}"
                            ))
                        except Exception as e:
                            self.stdout.write(self.style.ERROR(
                                f"✗ Failed to create symlink: {e}"
                            ))

                elif view_path.is_symlink():
                    # Verify symlink points to correct CAS file
                    try:
                        current_target = view_path.resolve()
                        if current_target != cas_path:
                            issues['incorrect_symlinks'].append((sf, view_name, view_path))

                            if fix:
                                ViewManager.create_symlinks_idempotent(sf, [view_name])
                                self.stdout.write(self.style.SUCCESS(
                                    f"✓ Fixed incorrect symlink: {view_path}"
                                ))
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(
                            f"✗ Broken symlink: {view_path} - {e}"
                        ))

        # Check 3: Find orphaned symlinks
        if vacuum:
            self.stdout.write("\n3. Checking for orphaned symlinks...")

            # Get all valid view paths from DB
            valid_paths = set()
            for sf in SnapshotFile.objects.all():
                for view_name in STORAGE_CONFIG.ENABLED_VIEWS:
                    view = ViewManager.VIEWS[view_name]
                    valid_paths.add(view.get_view_path(sf))

            # Scan filesystem for symlinks
            for view_name in STORAGE_CONFIG.ENABLED_VIEWS:
                view_base = CONSTANTS.ARCHIVE_DIR / view_name
                if not view_base.exists():
                    continue

                for path in view_base.rglob('*'):
                    if path.is_symlink() and path not in valid_paths:
                        issues['orphaned_symlinks'].append(path)

                        if fix:
                            path.unlink()
                            self.stdout.write(self.style.SUCCESS(
                                f"✓ Removed orphaned symlink: {path}"
                            ))

        # Check 4: Find orphaned blobs
        self.stdout.write("\n4. Checking for orphaned blobs...")
        orphaned_blobs = Blob.objects.filter(ref_count=0)

        for blob in orphaned_blobs:
            issues['orphaned_blobs'].append(blob)

            if fix:
                cas_path = ViewManager.get_cas_path(blob)
                if cas_path.exists():
                    cas_path.unlink()
                blob.delete()
                self.stdout.write(self.style.SUCCESS(
                    f"✓ Removed orphaned blob: {blob.hash[:16]}..."
                ))

        # Summary
        self.stdout.write("\n" + "="*80)
        self.stdout.write(self.style.WARNING("Storage Verification Summary:"))
        self.stdout.write(f"  Missing CAS files: {len(issues['missing_cas_files'])}")
        self.stdout.write(f"  Missing symlinks: {len(issues['missing_symlinks'])}")
        self.stdout.write(f"  Incorrect symlinks: {len(issues['incorrect_symlinks'])}")
        self.stdout.write(f"  Orphaned symlinks: {len(issues['orphaned_symlinks'])}")
        self.stdout.write(f"  Orphaned blobs: {len(issues['orphaned_blobs'])}")

        total_issues = sum(len(v) for v in issues.values())

        if total_issues == 0:
            self.stdout.write(self.style.SUCCESS("\n✓ Storage is consistent!"))
        elif fix:
            self.stdout.write(self.style.SUCCESS(f"\n✓ Fixed {total_issues} issues"))
        else:
            self.stdout.write(self.style.WARNING(
                f"\n⚠ Found {total_issues} issues. Run with --fix to repair."
            ))
```

## Configuration

```python
# archivebox/config/common.py

class StorageConfig(BaseConfigSet):
    toml_section_header: str = "STORAGE_CONFIG"

    # Existing fields
    TMP_DIR: Path = Field(default=CONSTANTS.DEFAULT_TMP_DIR)
    LIB_DIR: Path = Field(default=CONSTANTS.DEFAULT_LIB_DIR)
    OUTPUT_PERMISSIONS: str = Field(default="644")
    RESTRICT_FILE_NAMES: str = Field(default="windows")
    ENFORCE_ATOMIC_WRITES: bool = Field(default=True)
    DIR_OUTPUT_PERMISSIONS: str = Field(default="755")

    # New CAS fields
    USE_CAS: bool = Field(
        default=True,
        description="Use content-addressable storage with deduplication"
    )

    ENABLED_VIEWS: list[str] = Field(
        default=['by_timestamp', 'by_domain', 'by_date'],
        description="Which symlink farm views to maintain"
    )

    AUTO_SYNC_SYMLINKS: bool = Field(
        default=True,
        description="Automatically create/update symlinks via signals"
    )

    VERIFY_ON_STARTUP: bool = Field(
        default=False,
        description="Verify storage consistency on startup"
    )

    VERIFY_INTERVAL_HOURS: int = Field(
        default=24,
        description="Run periodic storage verification (0 to disable)"
    )

    CLEANUP_TEMP_FILES: bool = Field(
        default=True,
        description="Remove temporary extractor files after ingestion"
    )

    CAS_BACKEND: str = Field(
        default='local',
        choices=['local', 's3', 'azure', 'gcs'],
        description="Storage backend for CAS blobs"
    )
```

## Workflow Examples

### Example 1: Normal Operation

```python
# Extractor writes files to temporary directory
extractor_dir = Path('/tmp/wget-output')

# After extraction completes, ingest into CAS
from storage.ingest import BlobManager

ingested_files = BlobManager.ingest_directory(
    extractor_dir,
    snapshot,
    'wget'
)

# Behind the scenes:
# 1. Each file hashed (SHA-256)
# 2. Blob created/found in DB (deduplication)
# 3. File stored in CAS (if new)
# 4. SnapshotFile created in DB
# 5. post_save signal fires
# 6. Symlinks automatically created in all enabled views
# ✓ DB and filesystem in perfect sync
```

### Example 2: Browse Archives

```bash
# User can browse in multiple ways:

# By domain (great for site collections)
$ ls /data/archive/by_domain/example.com/20241225/
019b54ee-28d9-72dc/

# By date (great for time-based browsing)
$ ls /data/archive/by_date/20241225/
example.com/
github.com/
wikipedia.org/

# By user (great for multi-user setups)
$ ls /data/archive/by_user/squash/20241225/
example.com/
github.com/

# Legacy timestamp (backwards compatibility)
$ ls /data/archive/by_timestamp/1735142400.123/
wget/
singlefile/
screenshot/
```

### Example 3: Crash Recovery

```python
# System crashes after DB save but before symlinks created
# - DB has SnapshotFile record ✓
# - Symlinks missing ✗

# Next verification run:
$ python -m archivebox verify_storage --fix

# Output:
# Checking database → filesystem consistency...
# ✗ Missing symlink: /data/archive/by_domain/example.com/.../index.html
# ✓ Created missing symlink
# ✓ Fixed 1 issues

# Storage is now consistent!
```

### Example 4: Migration from Legacy

```bash
# Migrate all existing archives to CAS
$ python -m archivebox migrate_to_cas --dry-run

# Output:
# DRY RUN - No changes will be made
# Found 1000 snapshots to migrate
# [1/1000] Processing https://example.com...
#   Would ingest wget: 15 files
#   Would ingest singlefile: 1 file
# ...

# Run actual migration
$ python -m archivebox migrate_to_cas

# Output:
# [1/1000] Processing https://example.com...
#   ✓ Ingested 15 files (3 new, 12 deduplicated, saved 2.4 MB)
# ...
# Migration Complete!
#   Snapshots processed: 1000
#   Files ingested: 45,231
#   Space saved by deduplication: 12.3 GB
```

## Benefits

### Space Savings
- **Massive deduplication**: Common files (jquery, fonts, images) stored once
- **30-70% typical savings** across archives
- **Symlink overhead**: ~0.1% of saved space (negligible)

### Flexibility
- **Multiple views**: Browse by domain, date, user, timestamp
- **Add views anytime**: Run `rebuild_views` to add new organization
- **No data migration needed**: Just rebuild symlinks

### S3 Support
- **Use django-storages**: Drop-in S3, Azure, GCS support
- **Hybrid mode**: Hot data local, cold data in S3
- **Cost optimization**: S3 Intelligent Tiering for automatic cost reduction

### Data Integrity
- **Database as truth**: Symlinks are disposable, can be rebuilt
- **Automatic sync**: Signals keep symlinks current
- **Self-healing**: Verification detects and fixes drift
- **Atomic operations**: Transaction-safe

### Backwards Compatibility
- **Legacy view**: `by_timestamp` maintains old structure
- **Gradual migration**: Old and new archives coexist
- **Zero downtime**: Archives keep working during migration

### Developer Experience
- **Human-browseable**: Easy to inspect and debug
- **Standard tools work**: cp, rsync, tar, zip all work normally
- **Multiple organization schemes**: Find archives multiple ways
- **Easy backups**: Symlinks handled correctly by modern tools

## Implementation Checklist

- [ ] Create database models (Blob, SnapshotFile)
- [ ] Create migrations for new models
- [ ] Implement BlobManager (ingest.py)
- [ ] Implement ViewManager (views.py)
- [ ] Implement Django signals (signals.py)
- [ ] Create migrate_to_cas command
- [ ] Create rebuild_views command
- [ ] Create verify_storage command
- [ ] Update Snapshot.output_dir property
- [ ] Update ArchiveResult to use SnapshotFile
- [ ] Add StorageConfig settings
- [ ] Configure django-storages
- [ ] Test with local filesystem
- [ ] Test with S3
- [ ] Document for users
- [ ] Update backup procedures

## Future Enhancements

- [ ] Web UI for browsing CAS blobs
- [ ] API endpoints for file access
- [ ] Content-aware compression (compress similar files together)
- [ ] IPFS backend support
- [ ] Automatic tiering (hot → warm → cold → glacier)
- [ ] Deduplication statistics dashboard
- [ ] Export to WARC with CAS metadata
