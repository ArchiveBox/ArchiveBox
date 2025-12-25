#!/usr/bin/env python3
"""
Install a binary using pip package manager.

Usage: on_Dependency__install_using_pip_provider.py --dependency-id=<uuid> --bin-name=<name> [--custom-cmd=<cmd>]
Output: InstalledBinary JSONL record to stdout after installation

Environment variables:
    MACHINE_ID: Machine UUID (set by orchestrator)
"""

import json
import os
import sys

import rich_click as click
from abx_pkg import Binary, PipProvider, BinProviderOverrides

# Fix pydantic forward reference issue
PipProvider.model_rebuild()


@click.command()
@click.option('--dependency-id', required=True, help="Dependency UUID")
@click.option('--bin-name', required=True, help="Binary name to install")
@click.option('--bin-providers', default='*', help="Allowed providers (comma-separated)")
@click.option('--custom-cmd', default=None, help="Custom install command")
def main(dependency_id: str, bin_name: str, bin_providers: str, custom_cmd: str | None):
    """Install binary using pip."""

    if bin_providers != '*' and 'pip' not in bin_providers.split(','):
        click.echo(f"pip provider not allowed for {bin_name}", err=True)
        sys.exit(0)

    # Use abx-pkg PipProvider to install binary
    provider = PipProvider()
    if not provider.INSTALLER_BIN:
        click.echo("pip not available on this system", err=True)
        sys.exit(1)

    click.echo(f"Installing {bin_name} via pip...", err=True)

    try:
        binary = Binary(name=bin_name, binproviders=[provider]).install()
    except Exception as e:
        click.echo(f"pip install failed: {e}", err=True)
        sys.exit(1)

    if not binary.abspath:
        click.echo(f"{bin_name} not found after pip install", err=True)
        sys.exit(1)

    machine_id = os.environ.get('MACHINE_ID', '')

    # Output InstalledBinary JSONL record to stdout
    record = {
        'type': 'InstalledBinary',
        'name': bin_name,
        'abspath': str(binary.abspath),
        'version': str(binary.version) if binary.version else '',
        'sha256': binary.sha256 or '',
        'binprovider': 'pip',
        'machine_id': machine_id,
        'dependency_id': dependency_id,
    }
    print(json.dumps(record))

    # Log human-readable info to stderr
    click.echo(f"Installed {bin_name} at {binary.abspath}", err=True)
    click.echo(f"  version: {binary.version}", err=True)

    sys.exit(0)


if __name__ == '__main__':
    main()
