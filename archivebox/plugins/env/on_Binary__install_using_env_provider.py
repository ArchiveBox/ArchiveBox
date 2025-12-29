#!/usr/bin/env python3
"""
Check if a binary is already available in the system PATH.

This is the simplest "provider" - it doesn't install anything,
it just discovers binaries that are already installed.

Usage: on_Binary__install_using_env_provider.py --binary-id=<uuid> --machine-id=<uuid> --name=<name>
Output: Binary JSONL record to stdout if binary found in PATH

Environment variables:
    MACHINE_ID: Machine UUID (set by orchestrator)
"""

import json
import os
import sys

import rich_click as click
from abx_pkg import Binary, EnvProvider


@click.command()
@click.option('--machine-id', required=True, help="Machine UUID")
@click.option('--binary-id', required=True, help="Dependency UUID")
@click.option('--name', required=True, help="Binary name to find")
@click.option('--binproviders', default='*', help="Allowed providers (comma-separated)")
def main(binary_id: str, machine_id: str, name: str, binproviders: str):
    """Check if binary is available in PATH and record it."""

    # Check if env provider is allowed
    if binproviders != '*' and 'env' not in binproviders.split(','):
        click.echo(f"env provider not allowed for {name}", err=True)
        sys.exit(0)  # Not an error, just skip

    # Use abx-pkg EnvProvider to find binary
    provider = EnvProvider()
    try:
        binary = Binary(name=name, binproviders=[provider]).load()
    except Exception as e:
        click.echo(f"{name} not found in PATH: {e}", err=True)
        sys.exit(1)

    if not binary.abspath:
        click.echo(f"{name} not found in PATH", err=True)
        sys.exit(1)

    machine_id = os.environ.get('MACHINE_ID', '')

    # Output Binary JSONL record to stdout
    record = {
        'type': 'Binary',
        'name': name,
        'abspath': str(binary.abspath),
        'version': str(binary.version) if binary.version else '',
        'sha256': binary.sha256 or '',
        'binprovider': 'env',
        'machine_id': machine_id,
        'binary_id': binary_id,
    }
    print(json.dumps(record))

    # Log human-readable info to stderr
    click.echo(f"Found {name} at {binary.abspath}", err=True)
    click.echo(f"  version: {binary.version}", err=True)

    sys.exit(0)


if __name__ == '__main__':
    main()
