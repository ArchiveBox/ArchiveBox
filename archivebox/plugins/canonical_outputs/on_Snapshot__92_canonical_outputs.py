#!/usr/bin/env python3
"""
Create symlinks from plugin outputs to canonical legacy locations.

This plugin runs after all extractors complete and creates symlinks from the
new plugin-based output structure to the legacy canonical output paths that
ArchiveBox has historically used. This maintains backward compatibility with
existing tools and scripts that expect outputs at specific locations.

Canonical output paths:
    - favicon.ico → favicon/favicon.ico
    - singlefile.html → singlefile/singlefile.html
    - readability/content.html → readability/content.html
    - mercury/content.html → mercury/content.html
    - htmltotext.txt → htmltotext/htmltotext.txt
    - output.pdf → pdf/output.pdf
    - screenshot.png → screenshot/screenshot.png
    - output.html → dom/output.html
    - headers.json → headers/headers.json
    - warc/{timestamp} → wget/warc/{timestamp}

New plugin outputs:
    - ssl.json → ssl/ssl.json
    - seo.json → seo/seo.json
    - accessibility.json → accessibility/accessibility.json
    - outlinks.json → outlinks/outlinks.json
    - redirects.json → redirects/redirects.json
    - console.jsonl → consolelog/console.jsonl

Usage: on_Snapshot__92_canonical_outputs.py --url=<url> --snapshot-id=<uuid>

Environment variables:
    SAVE_CANONICAL_SYMLINKS: Enable canonical symlinks (default: true)
    DATA_DIR: ArchiveBox data directory
    ARCHIVE_DIR: Archive output directory
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict

import rich_click as click


# Mapping from canonical path to plugin output path
CANONICAL_MAPPINGS = {
    # Legacy extractors
    'favicon.ico': 'favicon/favicon.ico',
    'singlefile.html': 'singlefile/singlefile.html',
    'readability/content.html': 'readability/content.html',
    'mercury/content.html': 'mercury/content.html',
    'htmltotext.txt': 'htmltotext/htmltotext.txt',
    'output.pdf': 'pdf/output.pdf',
    'screenshot.png': 'screenshot/screenshot.png',
    'output.html': 'dom/output.html',
    'headers.json': 'headers/headers.json',

    # New plugins
    'ssl.json': 'ssl/ssl.json',
    'seo.json': 'seo/seo.json',
    'accessibility.json': 'accessibility/accessibility.json',
    'outlinks.json': 'parse_dom_outlinks/outlinks.json',
    'redirects.json': 'redirects/redirects.json',
    'console.jsonl': 'consolelog/console.jsonl',
}


def create_symlink(target: Path, link: Path, relative: bool = True) -> bool:
    """
    Create a symlink from link to target.

    Args:
        target: The actual file/directory (source)
        link: The symlink to create (destination)
        relative: Whether to create a relative symlink (default: True)

    Returns:
        True if symlink was created or already exists, False otherwise
    """
    try:
        # Skip if target doesn't exist
        if not target.exists():
            return False

        # Remove existing symlink/file if present
        if link.exists() or link.is_symlink():
            if link.is_symlink() and link.resolve() == target.resolve():
                # Already correctly symlinked
                return True
            link.unlink()

        # Create parent directory
        link.parent.mkdir(parents=True, exist_ok=True)

        # Create relative or absolute symlink
        if relative:
            # Calculate relative path from link to target
            rel_target = os.path.relpath(target, link.parent)
            link.symlink_to(rel_target)
        else:
            link.symlink_to(target)

        return True
    except (OSError, FileNotFoundError, PermissionError) as e:
        # Symlink creation failed, skip
        return False


def create_canonical_symlinks(snapshot_dir: Path) -> Dict[str, bool]:
    """
    Create all canonical symlinks for a snapshot directory.

    Args:
        snapshot_dir: The snapshot directory (e.g., archive/<timestamp>/)

    Returns:
        Dict mapping canonical path to success status
    """
    results = {}

    for canonical_path, plugin_output in CANONICAL_MAPPINGS.items():
        target = snapshot_dir / plugin_output
        link = snapshot_dir / canonical_path

        success = create_symlink(target, link, relative=True)
        results[canonical_path] = success

    # Special handling for warc/ directory symlink
    # wget plugin outputs to wget/warc/, but canonical expects warc/ at root
    wget_warc = snapshot_dir / 'wget' / 'warc'
    canonical_warc = snapshot_dir / 'warc'
    if wget_warc.exists():
        results['warc/'] = create_symlink(wget_warc, canonical_warc, relative=True)

    return results


@click.command()
@click.option('--url', required=True, help='URL being archived')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Create symlinks from plugin outputs to canonical legacy locations."""
    start_ts = datetime.now(timezone.utc)
    status = 'failed'
    output = None
    error = ''
    symlinks_created = 0

    try:
        # Check if enabled
        save_canonical = os.getenv('SAVE_CANONICAL_SYMLINKS', 'true').lower() in ('true', '1', 'yes', 'on')

        if not save_canonical:
            status = 'skipped'
            click.echo(json.dumps({'status': status, 'output': 'SAVE_CANONICAL_SYMLINKS=false'}))
            sys.exit(0)

        # Working directory is the extractor output dir (e.g., <snapshot>/canonical_outputs/)
        # Parent is the snapshot directory
        output_dir = Path.cwd()
        snapshot_dir = output_dir.parent

        if not snapshot_dir.exists():
            raise FileNotFoundError(f'Snapshot directory not found: {snapshot_dir}')

        # Create canonical symlinks
        results = create_canonical_symlinks(snapshot_dir)

        # Count successful symlinks
        symlinks_created = sum(1 for success in results.values() if success)
        total_mappings = len(results)

        status = 'succeeded'
        output = str(snapshot_dir)
        click.echo(f'Created {symlinks_created}/{total_mappings} canonical symlinks')

    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'
        click.echo(f'Error: {error}', err=True)

    end_ts = datetime.now(timezone.utc)

    # Print JSON result for hook runner
    result = {
        'status': status,
        'output': output,
        'error': error or None,
        'symlinks_created': symlinks_created,
    }
    click.echo(json.dumps(result))

    sys.exit(0 if status in ('succeeded', 'skipped') else 1)


if __name__ == '__main__':
    main()
