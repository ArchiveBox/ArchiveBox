"""
Folder status and integrity checking utilities for ArchiveBox.
"""

__package__ = 'archivebox.misc'

import os
import json
import shutil
from pathlib import Path
from itertools import chain
from typing import Dict, Optional, List, Tuple, TYPE_CHECKING

from django.db.models import QuerySet

from archivebox.config import DATA_DIR, CONSTANTS
from archivebox.misc.util import enforce_types

if TYPE_CHECKING:
    from core.models import Snapshot


def _is_valid_snapshot(snapshot: 'Snapshot') -> bool:
    """Check if a snapshot's data directory is valid"""
    dir_exists = Path(snapshot.output_dir).exists()
    index_exists = (Path(snapshot.output_dir) / "index.json").exists()
    if not dir_exists:
        return False
    if dir_exists and not index_exists:
        return False
    if dir_exists and index_exists:
        try:
            with open(Path(snapshot.output_dir) / "index.json", 'r') as f:
                data = json.load(f)
                return snapshot.url == data.get('url')
        except Exception:
            pass
    return False


def _is_corrupt_snapshot(snapshot: 'Snapshot') -> bool:
    """Check if a snapshot's data directory is corrupted"""
    if not Path(snapshot.output_dir).exists():
        return False
    return not _is_valid_snapshot(snapshot)


def get_indexed_folders(snapshots: QuerySet, out_dir: Path = DATA_DIR) -> Dict[str, 'Snapshot']:
    """indexed snapshots without checking archive status or data directory validity"""
    return {
        snapshot.output_dir: snapshot
        for snapshot in snapshots.iterator(chunk_size=500)
    }


def get_archived_folders(snapshots: QuerySet, out_dir: Path = DATA_DIR) -> Dict[str, 'Snapshot']:
    """indexed snapshots that are archived with a valid data directory"""
    return {
        snapshot.output_dir: snapshot
        for snapshot in snapshots.iterator(chunk_size=500)
        if snapshot.is_archived
    }


def get_unarchived_folders(snapshots: QuerySet, out_dir: Path = DATA_DIR) -> Dict[str, 'Snapshot']:
    """indexed snapshots that are unarchived with no data directory or an empty data directory"""
    return {
        snapshot.output_dir: snapshot
        for snapshot in snapshots.iterator(chunk_size=500)
        if not snapshot.is_archived
    }


def get_present_folders(snapshots: QuerySet, out_dir: Path = DATA_DIR) -> Dict[str, Optional['Snapshot']]:
    """dirs that actually exist in the archive/ folder"""
    from core.models import Snapshot

    all_folders = {}
    for entry in (out_dir / CONSTANTS.ARCHIVE_DIR_NAME).iterdir():
        if entry.is_dir():
            snapshot = None
            try:
                snapshot = Snapshot.objects.get(timestamp=entry.name)
            except Snapshot.DoesNotExist:
                pass
            all_folders[entry.name] = snapshot
    return all_folders


def get_valid_folders(snapshots: QuerySet, out_dir: Path = DATA_DIR) -> Dict[str, 'Snapshot']:
    """dirs with a valid index matched to the main index and archived content"""
    return {
        snapshot.output_dir: snapshot
        for snapshot in snapshots.iterator(chunk_size=500)
        if _is_valid_snapshot(snapshot)
    }


def get_invalid_folders(snapshots: QuerySet, out_dir: Path = DATA_DIR) -> Dict[str, Optional['Snapshot']]:
    """dirs that are invalid for any reason: corrupted/duplicate/orphaned/unrecognized"""
    duplicate = get_duplicate_folders(snapshots, out_dir=out_dir)
    orphaned = get_orphaned_folders(snapshots, out_dir=out_dir)
    corrupted = get_corrupted_folders(snapshots, out_dir=out_dir)
    unrecognized = get_unrecognized_folders(snapshots, out_dir=out_dir)
    return {**duplicate, **orphaned, **corrupted, **unrecognized}


def get_duplicate_folders(snapshots: QuerySet, out_dir: Path = DATA_DIR) -> Dict[str, Optional['Snapshot']]:
    """dirs that conflict with other directories that have the same URL or timestamp"""
    from core.models import Snapshot as SnapshotModel

    by_url: Dict[str, int] = {}
    by_timestamp: Dict[str, int] = {}
    duplicate_folders: Dict[str, Optional['Snapshot']] = {}

    data_folders = (
        str(entry)
        for entry in CONSTANTS.ARCHIVE_DIR.iterdir()
        if entry.is_dir() and not snapshots.filter(timestamp=entry.name).exists()
    )

    for item in chain(snapshots.iterator(chunk_size=500), data_folders):
        snapshot = None
        if isinstance(item, str):
            path = item
            timestamp = Path(path).name
            try:
                snapshot = SnapshotModel.objects.get(timestamp=timestamp)
            except SnapshotModel.DoesNotExist:
                pass
        else:
            snapshot = item
            path = snapshot.output_dir

        if snapshot:
            by_timestamp[snapshot.timestamp] = by_timestamp.get(snapshot.timestamp, 0) + 1
            if by_timestamp[snapshot.timestamp] > 1:
                duplicate_folders[path] = snapshot

            by_url[snapshot.url] = by_url.get(snapshot.url, 0) + 1
            if by_url[snapshot.url] > 1:
                duplicate_folders[path] = snapshot
    return duplicate_folders


def get_orphaned_folders(snapshots: QuerySet, out_dir: Path = DATA_DIR) -> Dict[str, Optional['Snapshot']]:
    """dirs that contain a valid index but aren't listed in the main index"""
    orphaned_folders: Dict[str, Optional['Snapshot']] = {}

    for entry in CONSTANTS.ARCHIVE_DIR.iterdir():
        if entry.is_dir():
            index_path = entry / "index.json"
            if index_path.exists() and not snapshots.filter(timestamp=entry.name).exists():
                orphaned_folders[str(entry)] = None
    return orphaned_folders


def get_corrupted_folders(snapshots: QuerySet, out_dir: Path = DATA_DIR) -> Dict[str, 'Snapshot']:
    """dirs that exist but have corrupted/invalid index files"""
    corrupted: Dict[str, 'Snapshot'] = {}
    for snapshot in snapshots.iterator(chunk_size=500):
        if _is_corrupt_snapshot(snapshot):
            corrupted[snapshot.output_dir] = snapshot
    return corrupted


def get_unrecognized_folders(snapshots: QuerySet, out_dir: Path = DATA_DIR) -> Dict[str, None]:
    """dirs that don't contain recognizable archive data and aren't listed in the main index"""
    unrecognized_folders: Dict[str, None] = {}

    for entry in (Path(out_dir) / CONSTANTS.ARCHIVE_DIR_NAME).iterdir():
        if entry.is_dir():
            index_exists = (entry / "index.json").exists()

            if index_exists:
                try:
                    with open(entry / "index.json", 'r') as f:
                        json.load(f)
                except Exception:
                    unrecognized_folders[str(entry)] = None
            else:
                timestamp = entry.name
                if not snapshots.filter(timestamp=timestamp).exists():
                    unrecognized_folders[str(entry)] = None
    return unrecognized_folders


@enforce_types
def fix_invalid_folder_locations(out_dir: Path = DATA_DIR) -> Tuple[List[str], List[str]]:
    """Move folders to their correct timestamp-named locations based on index.json"""
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
