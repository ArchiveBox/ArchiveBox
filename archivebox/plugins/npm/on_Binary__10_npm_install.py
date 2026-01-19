#!/usr/bin/env python3
"""
Install a binary using npm package manager.

Usage: on_Binary__install_using_npm_provider.py --binary-id=<uuid> --machine-id=<uuid> --name=<name> [--custom-cmd=<cmd>]
Output: Binary JSONL record to stdout after installation

Environment variables:
    MACHINE_ID: Machine UUID (set by orchestrator)
    LIB_DIR: Library directory including machine type (e.g., data/lib/arm64-darwin) (required)
"""

import json
import os
import sys
from pathlib import Path

import rich_click as click
from abx_pkg import Binary, NpmProvider, BinProviderOverrides

# Fix pydantic forward reference issue
NpmProvider.model_rebuild()


@click.command()
@click.option('--machine-id', required=True, help="Machine UUID")
@click.option('--binary-id', required=True, help="Dependency UUID")
@click.option('--name', required=True, help="Binary name to install")
@click.option('--binproviders', default='*', help="Allowed providers (comma-separated)")
@click.option('--custom-cmd', default=None, help="Custom install command")
@click.option('--overrides', default=None, help="JSON-encoded overrides dict")
def main(binary_id: str, machine_id: str, name: str, binproviders: str, custom_cmd: str | None, overrides: str | None):
    """Install binary using npm."""

    if binproviders != '*' and 'npm' not in binproviders.split(','):
        click.echo(f"npm provider not allowed for {name}", err=True)
        sys.exit(0)

    # Get LIB_DIR from environment (required)
    # Note: LIB_DIR already includes machine type (e.g., data/lib/arm64-darwin)
    lib_dir = os.environ.get('LIB_DIR')

    if not lib_dir:
        click.echo("ERROR: LIB_DIR environment variable not set", err=True)
        sys.exit(1)

    # Structure: lib/arm64-darwin/npm (npm will create node_modules inside this)
    npm_prefix = Path(lib_dir) / 'npm'
    npm_prefix.mkdir(parents=True, exist_ok=True)

    # Use abx-pkg NpmProvider to install binary with custom prefix
    provider = NpmProvider(npm_prefix=npm_prefix)
    if not provider.INSTALLER_BIN:
        click.echo("npm not available on this system", err=True)
        sys.exit(1)

    click.echo(f"Installing {name} via npm to {npm_prefix}...", err=True)

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
        click.echo(f"npm install failed: {e}", err=True)
        sys.exit(1)

    if not binary.abspath:
        click.echo(f"{name} not found after npm install", err=True)
        sys.exit(1)

    machine_id = os.environ.get('MACHINE_ID', '')

    # Output Binary JSONL record to stdout
    record = {
        'type': 'Binary',
        'name': name,
        'abspath': str(binary.abspath),
        'version': str(binary.version) if binary.version else '',
        'sha256': binary.sha256 or '',
        'binprovider': 'npm',
        'machine_id': machine_id,
        'binary_id': binary_id,
    }
    print(json.dumps(record))

    # Emit PATH update for npm bin dirs (node_modules/.bin preferred)
    npm_bin_dirs = [
        str(npm_prefix / 'node_modules' / '.bin'),
        str(npm_prefix / 'bin'),
    ]
    current_path = os.environ.get('PATH', '')
    path_dirs = current_path.split(':') if current_path else []
    new_path = current_path

    for npm_bin_dir in npm_bin_dirs:
        if npm_bin_dir and npm_bin_dir not in path_dirs:
            new_path = f"{npm_bin_dir}:{new_path}" if new_path else npm_bin_dir
            path_dirs.insert(0, npm_bin_dir)

    print(json.dumps({
        'type': 'Machine',
        'config': {
            'PATH': new_path,
        },
    }))

    # Also emit NODE_MODULES_DIR for JS module resolution
    node_modules_dir = str(npm_prefix / 'node_modules')
    print(json.dumps({
        'type': 'Machine',
        'config': {
            'NODE_MODULES_DIR': node_modules_dir,
        },
    }))

    # Log human-readable info to stderr
    click.echo(f"Installed {name} at {binary.abspath}", err=True)
    click.echo(f"  version: {binary.version}", err=True)

    sys.exit(0)


if __name__ == '__main__':
    main()
