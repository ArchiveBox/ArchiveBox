__package__ = 'archivebox.filestore'

import re
from pathlib import Path
from functools import wraps
from enum import Enum


import archivebox
from archivebox import CONSTANTS

from core.models import Snapshot
from .models import File


class FilestoreVersion(Enum):
    v0_7_2 = 'v0.7.2'
    v0_8_6 = 'v0.8.6'
    v0_9_0 = 'v0.9.0'

LATEST_VERSION = FilestoreVersion.v0_9_0


def migration(src_ver: FilestoreVersion, dst_ver: FilestoreVersion, pattern: str, timeout_seconds: int = 600):
    """Decorator for a migration function that will only run on files that match the given pattern and are at the given version."""
    def decorator(migration_func):
        @wraps(migration_func)
        def wrapper(file: File) -> None:
            # skip if this migration doesn't apply to this file
            if file.version != src_ver:
                return None
            if not re.match(pattern, file.file.name):
                return None
            
            # acquire lock, run migration + update version, then unlock
            try:
                file.acquire_lock(timeout_seconds)
                migration_func(file)
                file.version = dst_ver
            except Exception as e:
                # logger.error(f"Failed to migrate file {file.id}: {e}")
                print(f"Failed to migrate file {file.id}: {e}")
                file.version = src_ver             # roll back version to original version
            finally:
                file.release_lock()
                file.save()
            
        wrapper.src_ver = src_ver                  # type: ignore
        wrapper.dst_ver = dst_ver                  # type: ignore
        wrapper.pattern = pattern                  # type: ignore
        wrapper.timeout_seconds = timeout_seconds  # type: ignore
        return wrapper
    return decorator

def detect_archiveresult(path: Path) -> 'ArchiveResult' | None:
    # archive/1723423525.0/singlefile.html
    timestamp = path.parts[1]
    snapshot = Snapshot.objects.filter(timestamp=timestamp).last()
    if not snapshot:
        return
    
    result = snapshot.archiveresult_set.filter(output=path.name).last()
    if not result:
        return
    return result
    

# @hookimpl(hook_name='migrate_file')
@migration(FilestoreVersion.v0_7_2, FilestoreVersion.v0_8_6, r'archive/([0-9\.]+)/.+', timeout_seconds=600)
def migrate_v07_to_v08_singlefile(file: File) -> None:
    result = detect_archiveresult(file.relpath)
    new_path = result.OUTPUT_DIR / 'index.html'
    file.move_to(new_path)

# @hookimpl(hook_name='migrate_file')
@migration(FilestoreVersion.v0_8_6, FilestoreVersion.v0_9_0, r'archive/([0-9\.]+)/singlefile.html', timeout_seconds=600)
def migrate_v08_to_v09_singlefile(file: File) -> None:
    result = detect_archiveresult(file.relpath)
    new_path = result.OUTPUT_DIR / 'index.html'
    file.move_to(new_path)




def migrate_all_files(target=LATEST_VERSION, batch_size: int = 100):
    File.release_expired_locks()
    
    pending_files = (
        File.objects
            .filter(status='unlocked')
            .exclude(version=target)
            .iterator(chunk_size=batch_size)
    )
            
    for file in pending_files:
        try:
            archivebox.pm.hook.migrate_file(file=file)
        except Exception as e:
            print(f"Failed to migrate file {file.id}: {e}")
