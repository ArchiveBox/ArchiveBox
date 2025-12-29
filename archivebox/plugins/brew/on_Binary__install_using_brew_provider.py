#!/usr/bin/env python3
"""
Install a binary using Homebrew package manager.

Usage: on_Binary__install_using_brew_provider.py --binary-id=<uuid> --machine-id=<uuid> --name=<name> [--custom-cmd=<cmd>]
Output: Binary JSONL record to stdout after installation

Environment variables:
    MACHINE_ID: Machine UUID (set by orchestrator)
"""

import json
import os
import sys

import rich_click as click
from abx_pkg import Binary, BrewProvider, BinProviderOverrides

# Fix pydantic forward reference issue
BrewProvider.model_rebuild()


@click.command()
@click.option('--machine-id', required=True, help="Machine UUID")
@click.option('--binary-id', required=True, help="Dependency UUID")
@click.option('--name', required=True, help="Binary name to install")
@click.option('--binproviders', default='*', help="Allowed providers (comma-separated)")
@click.option('--custom-cmd', default=None, help="Custom install command")
@click.option('--overrides', default=None, help="JSON-encoded overrides dict")
def main(binary_id: str, machine_id: str, name: str, binproviders: str, custom_cmd: str | None, overrides: str | None):
    """Install binary using Homebrew."""

    if binproviders != '*' and 'brew' not in binproviders.split(','):
        click.echo(f"brew provider not allowed for {name}", err=True)
        sys.exit(0)

    # Use abx-pkg BrewProvider to install binary
    provider = BrewProvider()
    if not provider.INSTALLER_BIN:
        click.echo("brew not available on this system", err=True)
        sys.exit(1)

    click.echo(f"Installing {name} via brew...", err=True)

    try:
        # Parse overrides if provided
        overrides_dict = None
        if overrides:
            try:
                overrides_dict = json.loads(overrides)
                click.echo(f"Using custom install overrides: {overrides_dict}", err=True)
            except json.JSONDecodeError:
                click.echo(f"Warning: Failed to parse overrides JSON: {overrides}", err=True)

        binary = Binary(name=name, binproviders=[provider], overrides=overrides_dict or {}).install()
    except Exception as e:
        click.echo(f"brew install failed: {e}", err=True)
        sys.exit(1)

    if not binary.abspath:
        click.echo(f"{name} not found after brew install", err=True)
        sys.exit(1)

    machine_id = os.environ.get('MACHINE_ID', '')

    # Output Binary JSONL record to stdout
    record = {
        'type': 'Binary',
        'name': name,
        'abspath': str(binary.abspath),
        'version': str(binary.version) if binary.version else '',
        'sha256': binary.sha256 or '',
        'binprovider': 'brew',
        'machine_id': machine_id,
        'binary_id': binary_id,
    }
    print(json.dumps(record))

    # Log human-readable info to stderr
    click.echo(f"Installed {name} at {binary.abspath}", err=True)
    click.echo(f"  version: {binary.version}", err=True)

    sys.exit(0)


if __name__ == '__main__':
    main()
