"""
Ripgrep search backend - searches files directly without indexing.

This backend doesn't maintain an index - it searches archived files directly
using ripgrep (rg). This is simpler but slower for large archives.

Environment variables:
    RIPGREP_BINARY: Path to ripgrep binary (default: rg)
    RIPGREP_ARGS: Default ripgrep arguments (JSON array)
    RIPGREP_ARGS_EXTRA: Extra arguments to append (JSON array)
    RIPGREP_TIMEOUT: Search timeout in seconds (default: 90)
"""

import json
import os
import subprocess
import shutil
from pathlib import Path
from typing import List, Iterable


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


def get_env_array(name: str, default: list[str] | None = None) -> list[str]:
    """Parse a JSON array from environment variable."""
    val = get_env(name, '')
    if not val:
        return default if default is not None else []
    try:
        result = json.loads(val)
        if isinstance(result, list):
            return [str(item) for item in result]
        return default if default is not None else []
    except json.JSONDecodeError:
        return default if default is not None else []


def _get_archive_dir() -> Path:
    archive_dir = os.environ.get('ARCHIVE_DIR', '').strip()
    if archive_dir:
        return Path(archive_dir)
    data_dir = os.environ.get('DATA_DIR', '').strip()
    if data_dir:
        return Path(data_dir) / 'archive'
    return Path.cwd() / 'archive'


def search(query: str) -> List[str]:
    """Search for snapshots using ripgrep."""
    rg_binary = get_env('RIPGREP_BINARY', 'rg')
    rg_binary = shutil.which(rg_binary) or rg_binary
    if not rg_binary or not Path(rg_binary).exists():
        raise RuntimeError(f'ripgrep binary not found. Install with: apt install ripgrep')

    timeout = get_env_int('RIPGREP_TIMEOUT', 90)
    ripgrep_args = get_env_array('RIPGREP_ARGS', [])
    ripgrep_args_extra = get_env_array('RIPGREP_ARGS_EXTRA', [])

    archive_dir = _get_archive_dir()
    if not archive_dir.exists():
        return []

    cmd = [
        rg_binary,
        *ripgrep_args,
        *ripgrep_args_extra,
        '--regexp',
        query,
        str(archive_dir),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        # Extract snapshot IDs from file paths
        # Paths look like: archive/<snapshot_id>/<extractor>/file.txt
        snapshot_ids = set()
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            path = Path(line)
            try:
                relative = path.relative_to(archive_dir)
                snapshot_id = relative.parts[0]
                snapshot_ids.add(snapshot_id)
            except (ValueError, IndexError):
                continue

        return list(snapshot_ids)

    except subprocess.TimeoutExpired:
        return []
    except Exception:
        return []


def flush(snapshot_ids: Iterable[str]) -> None:
    """No-op for ripgrep - it searches files directly."""
    pass
