"""
Ripgrep search backend - searches files directly without indexing.

This backend doesn't maintain an index - it searches archived files directly
using ripgrep (rg). This is simpler but slower for large archives.

Environment variables:
    RIPGREP_BINARY: Path to ripgrep binary (default: rg)
    RIPGREP_IGNORE_EXTENSIONS: Comma-separated extensions to ignore (default: css,js,orig,svg)
    SEARCH_BACKEND_TIMEOUT: Search timeout in seconds (default: 90)
"""

import os
import subprocess
import shutil
from pathlib import Path
from typing import List, Iterable

from django.conf import settings


# Config with old var names for backwards compatibility
RIPGREP_BINARY = os.environ.get('RIPGREP_BINARY', 'rg').strip()
RIPGREP_IGNORE_EXTENSIONS = os.environ.get('RIPGREP_IGNORE_EXTENSIONS', 'css,js,orig,svg').strip()
SEARCH_BACKEND_TIMEOUT = int(os.environ.get('SEARCH_BACKEND_TIMEOUT', '90'))


def search(query: str) -> List[str]:
    """Search for snapshots using ripgrep."""
    rg_binary = shutil.which(RIPGREP_BINARY) or RIPGREP_BINARY
    if not rg_binary or not Path(rg_binary).exists():
        raise RuntimeError(f'ripgrep binary not found ({RIPGREP_BINARY}). Install with: apt install ripgrep')

    archive_dir = Path(settings.ARCHIVE_DIR)
    if not archive_dir.exists():
        return []

    # Build ignore pattern from config
    ignore_pattern = f'*.{{{RIPGREP_IGNORE_EXTENSIONS}}}'

    cmd = [
        rg_binary,
        f'--type-add=ignore:{ignore_pattern}',
        '--type-not=ignore',
        '--files-with-matches',
        '--no-messages',
        '--ignore-case',
        '--regexp',
        query,
        str(archive_dir),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=SEARCH_BACKEND_TIMEOUT)

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
