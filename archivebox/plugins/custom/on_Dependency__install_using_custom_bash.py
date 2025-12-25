#!/usr/bin/env python3
"""
Install a binary using a custom bash command.

This provider runs arbitrary shell commands to install binaries
that don't fit into standard package managers.

Usage: on_Dependency__install_using_custom_bash.py --dependency-id=<uuid> --bin-name=<name> --custom-cmd=<cmd>
Output: InstalledBinary JSONL record to stdout after installation

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
@click.option('--dependency-id', required=True, help="Dependency UUID")
@click.option('--bin-name', required=True, help="Binary name to install")
@click.option('--bin-providers', default='*', help="Allowed providers (comma-separated)")
@click.option('--custom-cmd', required=True, help="Custom bash command to run")
def main(dependency_id: str, bin_name: str, bin_providers: str, custom_cmd: str):
    """Install binary using custom bash command."""

    if bin_providers != '*' and 'custom' not in bin_providers.split(','):
        click.echo(f"custom provider not allowed for {bin_name}", err=True)
        sys.exit(0)

    if not custom_cmd:
        click.echo("custom provider requires --custom-cmd", err=True)
        sys.exit(1)

    click.echo(f"Installing {bin_name} via custom command: {custom_cmd}", err=True)

    try:
        result = subprocess.run(
            custom_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout for custom installs
        )
        if result.returncode != 0:
            click.echo(f"Custom install failed: {result.stderr}", err=True)
            sys.exit(1)
    except subprocess.TimeoutExpired:
        click.echo("Custom install timed out", err=True)
        sys.exit(1)

    # Use abx-pkg to load the installed binary and get its info
    provider = EnvProvider()
    try:
        binary = Binary(name=bin_name, binproviders=[provider]).load()
    except Exception as e:
        click.echo(f"{bin_name} not found after custom install: {e}", err=True)
        sys.exit(1)

    if not binary.abspath:
        click.echo(f"{bin_name} not found after custom install", err=True)
        sys.exit(1)

    machine_id = os.environ.get('MACHINE_ID', '')

    # Output InstalledBinary JSONL record to stdout
    record = {
        'type': 'InstalledBinary',
        'name': bin_name,
        'abspath': str(binary.abspath),
        'version': str(binary.version) if binary.version else '',
        'sha256': binary.sha256 or '',
        'binprovider': 'custom',
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
