__package__ = "archivebox.misc"

# Post-bootstrap filesystem utilities (atomic_write, get_dir_size).
# Requires archivebox.config (uses get_config for permissions/output settings).
# Not safe to import pre-bootstrap.

import os

from json import dump
from pathlib import Path

from atomicwrites import atomic_write as lib_atomic_write

from archivebox.config.common import get_config
from archivebox.misc.util import enforce_types, ExtendedEncoder


@enforce_types
def atomic_write(path: Path | str, contents: dict | str | bytes, overwrite: bool = True, config=None, **config_kwargs) -> None:
    """Safe atomic write to filesystem by writing to temp file + atomic rename"""

    mode = "wb+" if isinstance(contents, bytes) else "w"
    encoding = None if isinstance(contents, bytes) else "utf-8"  # enforce utf-8 on all text writes

    try:
        with lib_atomic_write(path, mode=mode, overwrite=overwrite, encoding=encoding) as f:
            if isinstance(contents, dict):
                dump(contents, f, indent=4, sort_keys=True, cls=ExtendedEncoder)
            elif isinstance(contents, (bytes, str)):
                f.write(contents)
    except OSError as e:
        config = config or get_config(**config_kwargs)
        if config.ENFORCE_ATOMIC_WRITES:
            print(f"[X] OSError: Failed to write {path} with fcntl.F_FULLFSYNC. ({e})")
            print(
                "    You can store the archive/ subfolder on a hard drive or network share that doesn't support support synchronous writes,",
            )
            print(
                "    but the main folder containing the index.sqlite3 and ArchiveBox.conf files must be on a filesystem that supports FSYNC.",
            )
            raise SystemExit(1)

        # retry the write without forcing FSYNC (aka atomic mode)
        with open(path, mode=mode, encoding=encoding) as f:
            if isinstance(contents, dict):
                dump(contents, f, indent=4, sort_keys=True, cls=ExtendedEncoder)
            elif isinstance(contents, (bytes, str)):
                f.write(contents)

    # set file permissions
    config = config or get_config(**config_kwargs)
    os.chmod(path, int(config.OUTPUT_PERMISSIONS, base=8))


@enforce_types
def get_dir_size(path: str | Path, recursive: bool = True, pattern: str | None = None) -> tuple[int, int, int]:
    """get the total disk size of a given directory, optionally summing up
    recursively and limiting to a given filter list
    """
    num_bytes, num_dirs, num_files = 0, 0, 0
    try:
        for entry in os.scandir(path):
            if (pattern is not None) and (pattern not in entry.path):
                continue
            if entry.is_dir(follow_symlinks=False):
                if not recursive:
                    continue
                num_dirs += 1
                bytes_inside, dirs_inside, files_inside = get_dir_size(entry.path)
                num_bytes += bytes_inside
                num_dirs += dirs_inside
                num_files += files_inside
            else:
                num_bytes += entry.stat(follow_symlinks=False).st_size
                num_files += 1
    except OSError:
        # e.g. FileNameTooLong or other error while trying to read dir
        pass
    return num_bytes, num_dirs, num_files
