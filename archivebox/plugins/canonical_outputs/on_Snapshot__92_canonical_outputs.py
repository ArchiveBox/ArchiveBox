#!/usr/bin/env python3
"""
Create symlinks from plugin outputs to canonical legacy locations.

This plugin runs after all extractors complete and creates symlinks from the
new plugin-based output structure to the legacy canonical output paths that
ArchiveBox has historically used. This maintains backward compatibility with
existing tools and scripts that expect outputs at specific locations.

Canonical output paths (from Snapshot.canonical_outputs()):
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

Usage: on_Snapshot__91_canonical_outputs.py --url=<url> --snapshot-id=<uuid>

Environment variables:
    SAVE_CANONICAL_SYMLINKS: Enable canonical symlinks (default: true)
"""

__package__ = 'archivebox.plugins.canonical_outputs'

import os
import sys
from pathlib import Path
from typing import Dict, Optional

# Configure Django if running standalone
if __name__ == '__main__':
    parent_dir = str(Path(__file__).resolve().parent.parent.parent)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
    import django
    django.setup()

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
    from datetime import datetime
    from archivebox.core.models import Snapshot

    start_ts = datetime.now()
    status = 'failed'
    output = None
    error = ''
    symlinks_created = 0

    try:
        # Check if enabled
        from archivebox.config import CONSTANTS
        save_canonical = os.getenv('SAVE_CANONICAL_SYMLINKS', 'true').lower() in ('true', '1', 'yes', 'on')

        if not save_canonical:
            click.echo('Skipping canonical symlinks (SAVE_CANONICAL_SYMLINKS=False)')
            status = 'skipped'
            end_ts = datetime.now()
            click.echo(f'START_TS={start_ts.isoformat()}')
            click.echo(f'END_TS={end_ts.isoformat()}')
            click.echo(f'STATUS={status}')
            click.echo(f'RESULT_JSON={{"extractor": "canonical_outputs", "status": "{status}", "url": "{url}", "snapshot_id": "{snapshot_id}"}}')
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
    import json
    result_json = {
        'extractor': 'canonical_outputs',
        'url': url,
        'snapshot_id': snapshot_id,
        'status': status,
        'start_ts': start_ts.isoformat(),
        'end_ts': end_ts.isoformat(),
        'duration': round(duration, 2),
        'output': output,
        'symlinks_created': symlinks_created,
        'error': error or None,
    }
    click.echo(f'RESULT_JSON={json.dumps(result_json)}')

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
