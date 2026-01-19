#!/usr/bin/env python3
"""
Install a binary using a custom bash command.

This provider runs arbitrary shell commands to install binaries
that don't fit into standard package managers.

Usage: on_Binary__install_using_custom_bash.py --binary-id=<uuid> --machine-id=<uuid> --name=<name> --custom-cmd=<cmd>
Output: Binary JSONL record to stdout after installation

Environment variables:
    MACHINE_ID: Machine UUID (set by orchestrator)
"""

import json
import os
import subprocess
import sys

import rich_click as click
from abx_pkg import Binary, EnvProvider


@click.command()
@click.option('--binary-id', required=True, help="Binary UUID")
@click.option('--machine-id', required=True, help="Machine UUID")
@click.option('--name', required=True, help="Binary name to install")
@click.option('--binproviders', default='*', help="Allowed providers (comma-separated)")
@click.option('--custom-cmd', required=True, help="Custom bash command to run")
def main(binary_id: str, machine_id: str, name: str, binproviders: str, custom_cmd: str):
    """Install binary using custom bash command."""

    if binproviders != '*' and 'custom' not in binproviders.split(','):
        click.echo(f"custom provider not allowed for {name}", err=True)
        sys.exit(0)

    if not custom_cmd:
        click.echo("custom provider requires --custom-cmd", err=True)
        sys.exit(1)

    click.echo(f"Installing {name} via custom command: {custom_cmd}", err=True)

    try:
        result = subprocess.run(
            custom_cmd,
            shell=True,
            timeout=600,  # 10 minute timeout for custom installs
        )
        if result.returncode != 0:
            click.echo(f"Custom install failed (exit={result.returncode})", err=True)
            sys.exit(1)
    except subprocess.TimeoutExpired:
        click.echo("Custom install timed out", err=True)
        sys.exit(1)

    # Use abx-pkg to load the binary and get its info
    provider = EnvProvider()
    try:
        binary = Binary(name=name, binproviders=[provider]).load()
    except Exception:
        try:
            binary = Binary(
                name=name,
                binproviders=[provider],
                overrides={'env': {'version': '0.0.1'}},
            ).load()
        except Exception as e:
            click.echo(f"{name} not found after custom install: {e}", err=True)
            sys.exit(1)

    if not binary.abspath:
        click.echo(f"{name} not found after custom install", err=True)
        sys.exit(1)

    machine_id = os.environ.get('MACHINE_ID', '')

    # Output Binary JSONL record to stdout
    record = {
        'type': 'Binary',
        'name': name,
        'abspath': str(binary.abspath),
        'version': str(binary.version) if binary.version else '',
        'sha256': binary.sha256 or '',
        'binprovider': 'custom',
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
