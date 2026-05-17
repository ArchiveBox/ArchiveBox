"""
Folder utilities for ArchiveBox.

Note: This file only contains legacy cleanup utilities.
The DB is the single source of truth - use Snapshot.objects queries for all status checks.
"""

__package__ = "archivebox.misc"

import os
import json
import shutil
from pathlib import Path

from archivebox.config import DATA_DIR, CONSTANTS
from archivebox.config.common import get_config
from archivebox.misc.util import enforce_types


@enforce_types
def fix_invalid_folder_locations(out_dir: Path = DATA_DIR, config=None, **config_kwargs) -> tuple[list[str], list[str]]:
    """
    Legacy cleanup: Move folders to their correct timestamp-named locations based on index.json.

    This is only used during 'archivebox init' for one-time cleanup of misnamed directories.
    After this runs once, 'archivebox update' handles all filesystem operations.
    """
    fixed = []
    cant_fix = []
    config = config or get_config(**config_kwargs)
    archive_dir = config.ARCHIVE_DIR if Path(out_dir).resolve() == DATA_DIR.resolve() else out_dir / CONSTANTS.ARCHIVE_DIR_NAME
    if not archive_dir.exists():
        return fixed, cant_fix
    for entry in os.scandir(archive_dir):
        entry_path = Path(entry.path)
        if entry_path.name in CONSTANTS.RESERVED_ARCHIVE_DIR_NAMES or entry_path.name.startswith("."):
            continue
        if entry.is_dir(follow_symlinks=True):
            index_path = entry_path / "index.json"
            if index_path.exists():
                try:
                    with open(index_path) as f:
                        data = json.load(f)
                    timestamp = data.get("timestamp")
                except Exception:
                    continue

                if not timestamp:
                    continue

                if not entry.path.endswith(f"/{timestamp}"):
                    dest = archive_dir / timestamp
                    if dest.exists():
                        cant_fix.append(entry.path)
                    else:
                        shutil.move(entry.path, str(dest))
                        fixed.append(str(dest))
    return fixed, cant_fix
