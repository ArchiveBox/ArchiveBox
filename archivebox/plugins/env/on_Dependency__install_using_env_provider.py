#!/usr/bin/env python3
"""
Check if a binary is already available in the system PATH.

This is the simplest "provider" - it doesn't install anything,
it just discovers binaries that are already installed.

Usage: on_Dependency__install_using_env_provider.py --dependency-id=<uuid> --bin-name=<name>
Output: InstalledBinary JSONL record to stdout if binary found in PATH

Environment variables:
    MACHINE_ID: Machine UUID (set by orchestrator)
"""

import json
import os
import sys

import rich_click as click
from abx_pkg import Binary, EnvProvider


@click.command()
@click.option('--dependency-id', required=True, help="Dependency UUID")
@click.option('--bin-name', required=True, help="Binary name to find")
@click.option('--bin-providers', default='*', help="Allowed providers (comma-separated)")
def main(dependency_id: str, bin_name: str, bin_providers: str):
    """Check if binary is available in PATH and record it."""

    # Check if env provider is allowed
    if bin_providers != '*' and 'env' not in bin_providers.split(','):
        click.echo(f"env provider not allowed for {bin_name}", err=True)
        sys.exit(0)  # Not an error, just skip

    # Use abx-pkg EnvProvider to find binary
    provider = EnvProvider()
    try:
        binary = Binary(name=bin_name, binproviders=[provider]).load()
    except Exception as e:
        click.echo(f"{bin_name} not found in PATH: {e}", err=True)
        sys.exit(1)

    if not binary.abspath:
        click.echo(f"{bin_name} not found in PATH", err=True)
        sys.exit(1)

    machine_id = os.environ.get('MACHINE_ID', '')

    # Output InstalledBinary JSONL record to stdout
    record = {
        'type': 'InstalledBinary',
        'name': bin_name,
        'abspath': str(binary.abspath),
        'version': str(binary.version) if binary.version else '',
        'sha256': binary.sha256 or '',
        'binprovider': 'env',
        'machine_id': machine_id,
        'dependency_id': dependency_id,
    }
    print(json.dumps(record))

    # Log human-readable info to stderr
    click.echo(f"Found {bin_name} at {binary.abspath}", err=True)
    click.echo(f"  version: {binary.version}", err=True)

    sys.exit(0)


if __name__ == '__main__':
    main()
