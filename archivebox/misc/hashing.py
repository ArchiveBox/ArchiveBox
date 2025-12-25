import hashlib
import mimetypes
from functools import lru_cache
from pathlib import Path
from typing import Callable
from datetime import datetime

@lru_cache(maxsize=1024)
def _cached_file_hash(filepath: str, size: int, mtime: float) -> str:
    """Internal function to calculate file hash with cache key based on path, size and mtime."""
    sha256_hash = hashlib.sha256()

    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            sha256_hash.update(chunk)

    return sha256_hash.hexdigest()

@lru_cache(maxsize=10)
def hash_file(file_path: Path, pwd: Path | None = None) -> str:
    """Calculate SHA256 hash of a file with caching based on path, size and mtime."""
    pwd = Path(pwd) if pwd else None
    file_path = Path(file_path)
    if not file_path.is_absolute():
        file_path = pwd / file_path if pwd else file_path.absolute()

    abs_path = file_path.resolve()
    stat_info = abs_path.stat()

    return _cached_file_hash(
        str(abs_path),
        stat_info.st_size,
        stat_info.st_mtime
    )

@lru_cache(maxsize=10)
def get_dir_hashes(dir_path: Path, pwd: Path | None = None, filter_func: Callable | None = None, max_depth: int = -1) -> dict[str, str]:
    """Calculate SHA256 hashes for all files and directories recursively."""
    pwd = Path(pwd) if pwd else None
    dir_path = Path(dir_path)
    if not dir_path.is_absolute():
        dir_path = pwd / dir_path if pwd else dir_path.absolute()

    if not dir_path.is_dir():
        raise ValueError(f"Not a directory: {dir_path}")
    if max_depth < -1:
        raise ValueError(f"max_depth must be >= -1, got {max_depth}")

    # Get all files recursively
    all_files = get_dir_entries(
        dir_path, pwd=pwd, recursive=True,
        include_files=True, include_dirs=False,
        filter_func=filter_func
    )

    hashes: dict[str, str] = {}
    hashable_summary = []

    # Calculate hashes for all files
    for subfile in all_files:
        subfile_path = dir_path / subfile
        sha256_hash = hash_file(subfile_path)
        hashes[subfile] = sha256_hash
        hashable_summary.append(f"{sha256_hash}  ./{subfile}")

    # Calculate hashes for all directories
    subdirs = get_dir_entries(
        dir_path, pwd=pwd, recursive=True,
        include_files=False, include_dirs=True,
        include_hidden=False, filter_func=filter_func,
        max_depth=max_depth
    )

    for subdir in subdirs:
        subdir_path = dir_path / subdir
        subdir_hashes = get_dir_hashes(
            subdir_path, filter_func=filter_func,
            max_depth=0
        )
        hashes[subdir] = subdir_hashes['.']

    # Filter results by max_depth
    if max_depth >= 0:
        hashes = {
            path: value for path, value in hashes.items()
            if len(Path(path).parts) <= max_depth + 1
        }

    # Calculate root directory hash
    hashable_summary.sort()
    root_sha256 = hashlib.sha256('\n'.join(hashable_summary).encode()).hexdigest()
    hashes['.'] = root_sha256

    return hashes


@lru_cache(maxsize=128)
def get_dir_entries(dir_path: Path, pwd: Path | None = None, recursive: bool = True,
                    include_files: bool = True, include_dirs: bool = True, include_hidden: bool = False,
                    filter_func: Callable | None = None, max_depth: int = -1) -> tuple[str, ...]:
    """Get filtered list of directory entries."""
    pwd = Path(pwd) if pwd else None
    dir_path = Path(dir_path)
    if not dir_path.is_absolute():
        dir_path = pwd / dir_path if pwd else dir_path.absolute()

    results = []

    def process_path(path: Path, depth: int):
        if not include_hidden and path.name.startswith('.'):
            return False
        if max_depth >= 0 and depth > max_depth:
            return False
        if filter_func:
            info = {
                "abspath": str(path.absolute()),
                "relpath": str(path.relative_to(dir_path))
            }
            if not filter_func(info):
                return False
        return True

    for path in dir_path.rglob('*') if recursive else dir_path.glob('*'):
        current_depth = len(path.relative_to(dir_path).parts)

        if path.is_file() and include_files and process_path(path, current_depth):
            results.append(str(path.relative_to(dir_path)))
        elif path.is_dir() and include_dirs and process_path(path, current_depth):
            results.append(str(path.relative_to(dir_path)))

        if not recursive:
            break

    return tuple(sorted(results))  # Make immutable for caching

@lru_cache(maxsize=1024)
def get_dir_sizes(dir_path: Path, pwd: Path | None = None, **kwargs) -> dict[str, int]:
    """Calculate sizes for all files and directories recursively."""
    sizes: dict[str, int] = {}
    hashes = get_dir_hashes(dir_path, pwd=pwd, **kwargs)
    dir_path = Path(dir_path)

    for path_key in hashes:
        full_path = dir_path / path_key
        if full_path.is_file():
            sizes[path_key] = full_path.stat().st_size
        else:
            total = 0
            for file_path in full_path.rglob('*'):
                if file_path.is_file() and not file_path.name.startswith('.'):
                    total += file_path.stat().st_size
            sizes[path_key + '/'] = total

    return sizes


@lru_cache(maxsize=10)
def get_dir_info(dir_path: Path, pwd: Path | None = None, filter_func: Callable | None = None, max_depth: int = -1) -> dict:
    """Get detailed information about directory contents including hashes and sizes."""
    pwd = Path(pwd) if pwd else None
    dir_path = Path(dir_path)
    if not dir_path.is_absolute():
        dir_path = pwd / dir_path if pwd else dir_path.absolute()

    hashes = get_dir_hashes(dir_path, pwd=pwd, filter_func=filter_func, max_depth=max_depth)
    sizes = get_dir_sizes(str(dir_path), pwd=pwd, filter_func=filter_func, max_depth=max_depth)

    num_total_subpaths = sum(1 for name in hashes if name != '.')
    details = {}

    for filename, sha256_hash in sorted(hashes.items()):
        abs_path = (dir_path / filename).resolve()
        stat_info = abs_path.stat()
        num_subpaths = sum(1 for p in hashes if p.startswith(filename + '/'))
        is_dir = abs_path.is_dir()
        if is_dir:
            mime_type = 'inode/directory'
            basename = abs_path.name
            extension = ''
            num_bytes = sizes[filename + '/']
            if filename == '.':
                num_subpaths = num_total_subpaths
            else:
                filename += '/'
                num_subpaths = num_subpaths
        else:  # is_file
            num_subpaths = None
            mime_type = mimetypes.guess_type(str(abs_path))[0]
            extension = abs_path.suffix
            basename = abs_path.name.rsplit(extension, 1)[0]
            num_bytes = sizes[filename]

        details[filename] = {
            'basename': basename,
            'mime_type': mime_type,
            'extension': extension,
            'num_subpaths': num_subpaths,
            'num_bytes': num_bytes,
            'hash_sha256': sha256_hash,
            'created_at': datetime.fromtimestamp(stat_info.st_ctime).isoformat(),
            'modified_at': datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
        }

        if filter_func and not filter_func(details[filename]):
            del details[filename]

    return details


if __name__ == '__main__':
    import json
    dir_info = get_dir_info(Path('.'), max_depth=6)
    with open('.hashes.json', 'w') as f:
        json.dump(dir_info, f, indent=4)
    print('Wrote .hashes.json')

# Example output:
# {
#     ".": {
#         "basename": "misc",
#         "mime_type": "inode/directory",
#         "extension": "",
#         "num_subpaths": 25,
#         "num_bytes": 214677,
#         "hash_sha256": "addfacf88b2ff6b564846415fb7b21dcb7e63ee4e911bc0aec255ee354958530",
#         "created_at": "2024-12-04T00:08:38.537449",
#         "modified_at": "2024-12-04T00:08:38.537449"
#     },
#     "__init__.py": {
#         "basename": "__init__",
#         "mime_type": "text/x-python",
#         "extension": ".py",
#         "num_subpaths": null,
#         "num_bytes": 32,
#         "hash_sha256": "b0e5e7ff17db3b60535cf664282787767c336e3e203a43e21b6326c6fe457551",
#         "created_at": "2024-10-08T00:51:41.001359",
#         "modified_at": "2024-10-08T00:51:41.001359"
#     },
#     ...
# }
