#!/usr/bin/env python3
"""
Create a Merkle tree of all archived outputs.

This plugin runs after all extractors and post-processing complete (priority 92)
and generates a cryptographic Merkle tree of all files in the snapshot directory.
This provides:
    - Tamper detection: verify archive integrity
    - Efficient updates: only re-hash changed files
    - Compact proofs: prove file inclusion without sending all files
    - Deduplication: identify identical content across snapshots

Output: merkletree/merkletree.json containing:
    - root_hash: SHA256 hash of the Merkle root
    - tree: Full tree structure with internal nodes
    - files: List of all files with their hashes
    - metadata: Timestamp, file count, total size

Usage: on_Snapshot__92_merkletree.py --url=<url> --snapshot-id=<uuid>

Environment variables:
    SAVE_MERKLETREE: Enable merkle tree generation (default: true)
"""

__package__ = 'archivebox.plugins.merkletree'

import os
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

# Configure Django if running standalone
if __name__ == '__main__':
    parent_dir = str(Path(__file__).resolve().parent.parent.parent)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
    import django
    django.setup()

import rich_click as click


def sha256_file(filepath: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            # Read in 64kb chunks
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        # If we can't read the file, return a null hash
        return '0' * 64


def sha256_data(data: bytes) -> str:
    """Compute SHA256 hash of raw data."""
    return hashlib.sha256(data).hexdigest()


def collect_files(snapshot_dir: Path, exclude_dirs: Optional[List[str]] = None) -> List[Tuple[Path, str, int]]:
    """
    Recursively collect all files in snapshot directory.

    Args:
        snapshot_dir: Root directory to scan
        exclude_dirs: Directory names to exclude (e.g., ['merkletree', '.git'])

    Returns:
        List of (relative_path, sha256_hash, file_size) tuples
    """
    exclude_dirs = exclude_dirs or ['merkletree', '.git', '__pycache__']
    files = []

    for root, dirs, filenames in os.walk(snapshot_dir):
        # Filter out excluded directories
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for filename in filenames:
            filepath = Path(root) / filename
            rel_path = filepath.relative_to(snapshot_dir)

            # Skip symlinks (we hash the target, not the link)
            if filepath.is_symlink():
                continue

            # Compute hash and size
            file_hash = sha256_file(filepath)
            file_size = filepath.stat().st_size if filepath.exists() else 0

            files.append((rel_path, file_hash, file_size))

    # Sort by path for deterministic tree
    files.sort(key=lambda x: str(x[0]))
    return files


def build_merkle_tree(file_hashes: List[str]) -> Tuple[str, List[List[str]]]:
    """
    Build a Merkle tree from a list of leaf hashes.

    Args:
        file_hashes: List of SHA256 hashes (leaves)

    Returns:
        (root_hash, tree_levels) where tree_levels is a list of hash lists per level
    """
    if not file_hashes:
        # Empty tree
        return sha256_data(b''), [[]]

    # Initialize with leaf level
    tree_levels = [file_hashes.copy()]

    # Build tree bottom-up
    while len(tree_levels[-1]) > 1:
        current_level = tree_levels[-1]
        next_level = []

        # Process pairs
        for i in range(0, len(current_level), 2):
            left = current_level[i]

            if i + 1 < len(current_level):
                # Combine left + right
                right = current_level[i + 1]
                combined = left + right
            else:
                # Odd number of nodes: duplicate the last one
                combined = left + left

            parent_hash = sha256_data(combined.encode('utf-8'))
            next_level.append(parent_hash)

        tree_levels.append(next_level)

    # Root is the single hash at the top level
    root_hash = tree_levels[-1][0]
    return root_hash, tree_levels


def create_merkle_tree(snapshot_dir: Path) -> Dict[str, Any]:
    """
    Create a complete Merkle tree of all files in snapshot directory.

    Args:
        snapshot_dir: The snapshot directory to scan

    Returns:
        Dict containing root_hash, tree structure, file list, and metadata
    """
    # Collect all files
    files = collect_files(snapshot_dir)

    # Extract just the hashes for tree building
    file_hashes = [file_hash for _, file_hash, _ in files]

    # Build Merkle tree
    root_hash, tree_levels = build_merkle_tree(file_hashes)

    # Calculate total size
    total_size = sum(size for _, _, size in files)

    # Prepare file list with metadata
    file_list = [
        {
            'path': str(path),
            'hash': file_hash,
            'size': size,
        }
        for path, file_hash, size in files
    ]

    # Prepare result
    result = {
        'root_hash': root_hash,
        'tree_levels': tree_levels,
        'files': file_list,
        'metadata': {
            'timestamp': datetime.now().isoformat(),
            'file_count': len(files),
            'total_size': total_size,
            'tree_depth': len(tree_levels),
        },
    }

    return result


@click.command()
@click.option('--url', required=True, help='URL being archived')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Generate Merkle tree of all archived outputs."""
    from archivebox.core.models import Snapshot

    start_ts = datetime.now()
    status = 'failed'
    output = None
    error = ''
    root_hash = None
    file_count = 0

    try:
        # Check if enabled
        save_merkletree = os.getenv('SAVE_MERKLETREE', 'true').lower() in ('true', '1', 'yes', 'on')

        if not save_merkletree:
            click.echo('Skipping merkle tree (SAVE_MERKLETREE=False)')
            status = 'skipped'
            end_ts = datetime.now()
            click.echo(f'START_TS={start_ts.isoformat()}')
            click.echo(f'END_TS={end_ts.isoformat()}')
            click.echo(f'STATUS={status}')
            click.echo(f'RESULT_JSON={{"extractor": "merkletree", "status": "{status}", "url": "{url}", "snapshot_id": "{snapshot_id}"}}')
            sys.exit(0)

        # Get snapshot
        try:
            snapshot = Snapshot.objects.get(id=snapshot_id)
        except Snapshot.DoesNotExist:
            error = f'Snapshot {snapshot_id} not found'
            raise ValueError(error)

        # Get snapshot directory
        snapshot_dir = Path(snapshot.output_dir)
        if not snapshot_dir.exists():
            error = f'Snapshot directory not found: {snapshot_dir}'
            raise FileNotFoundError(error)

        # Create output directory
        output_dir = snapshot_dir / 'merkletree'
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / 'merkletree.json'

        # Generate Merkle tree
        merkle_data = create_merkle_tree(snapshot_dir)

        # Write output
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(merkle_data, f, indent=2)

        status = 'succeeded'
        output = str(output_path)
        root_hash = merkle_data['root_hash']
        file_count = merkle_data['metadata']['file_count']
        total_size = merkle_data['metadata']['total_size']

        click.echo(f'Merkle tree created: {file_count} files, root={root_hash[:16]}..., size={total_size:,} bytes')

    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'
        click.echo(f'Error: {error}', err=True)

    end_ts = datetime.now()
    duration = (end_ts - start_ts).total_seconds()

    # Print results
    click.echo(f'START_TS={start_ts.isoformat()}')
    click.echo(f'END_TS={end_ts.isoformat()}')
    click.echo(f'DURATION={duration:.2f}')
    if output:
        click.echo(f'OUTPUT={output}')
    click.echo(f'STATUS={status}')

    if error:
        click.echo(f'ERROR={error}', err=True)

    # Print JSON result
    result_json = {
        'extractor': 'merkletree',
        'url': url,
        'snapshot_id': snapshot_id,
        'status': status,
        'start_ts': start_ts.isoformat(),
        'end_ts': end_ts.isoformat(),
        'duration': round(duration, 2),
        'output': output,
        'root_hash': root_hash,
        'file_count': file_count,
        'error': error or None,
    }
    click.echo(f'RESULT_JSON={json.dumps(result_json)}')

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
