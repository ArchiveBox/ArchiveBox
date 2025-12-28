#!/usr/bin/env python3
"""
Install a binary using pip package manager.

Usage: on_Binary__install_using_pip_provider.py --binary-id=<uuid> --machine-id=<uuid> --name=<name>
Output: Binary JSONL record to stdout after installation
"""

import json
import sys

import rich_click as click
from abx_pkg import Binary, PipProvider

# Fix pydantic forward reference issue
PipProvider.model_rebuild()


@click.command()
@click.option('--binary-id', required=True, help="Binary UUID")
@click.option('--machine-id', required=True, help="Machine UUID")
@click.option('--name', required=True, help="Binary name to install")
@click.option('--binproviders', default='*', help="Allowed providers (comma-separated)")
@click.option('--overrides', default=None, help="JSON-encoded overrides dict")
def main(binary_id: str, machine_id: str, name: str, binproviders: str, overrides: str | None):
    """Install binary using pip."""

    # Check if pip provider is allowed
    if binproviders != '*' and 'pip' not in binproviders.split(','):
        click.echo(f"pip provider not allowed for {name}", err=True)
        sys.exit(0)

    # Use abx-pkg PipProvider to install binary
    provider = PipProvider()
    if not provider.INSTALLER_BIN:
        click.echo("pip not available on this system", err=True)
        sys.exit(1)

    click.echo(f"Installing {name} via pip...", err=True)

    try:
        # Parse overrides if provided
        overrides_dict = None
        if overrides:
            try:
                overrides_dict = json.loads(overrides)
                # Extract pip-specific overrides
                overrides_dict = overrides_dict.get('pip', {})
                click.echo(f"Using pip install overrides: {overrides_dict}", err=True)
            except json.JSONDecodeError:
                click.echo(f"Warning: Failed to parse overrides JSON: {overrides}", err=True)

        binary = Binary(name=name, binproviders=[provider], overrides={'pip': overrides_dict} if overrides_dict else {}).install()
    except Exception as e:
        click.echo(f"pip install failed: {e}", err=True)
        sys.exit(1)

    if not binary.abspath:
        click.echo(f"{name} not found after pip install", err=True)
        sys.exit(1)

    # Output Binary JSONL record to stdout
    record = {
        'type': 'Binary',
        'name': name,
        'abspath': str(binary.abspath),
        'version': str(binary.version) if binary.version else '',
        'sha256': binary.sha256 or '',
        'binprovider': 'pip',
    }
    print(json.dumps(record))

    # Log human-readable info to stderr
    click.echo(f"Installed {name} at {binary.abspath}", err=True)
    click.echo(f"  version: {binary.version}", err=True)

    sys.exit(0)


if __name__ == '__main__':
    main()
