#!/usr/bin/env python3
"""
Install a binary using pip package manager.

Usage: on_Binary__install_using_pip_provider.py --binary-id=<uuid> --machine-id=<uuid> --name=<name>
Output: Binary JSONL record to stdout after installation

Environment variables:
    LIB_DIR: Library directory including machine type (e.g., data/lib/arm64-darwin) (required)
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import rich_click as click
from abx_pkg import Binary, PipProvider, BinProviderOverrides

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

    # Get LIB_DIR from environment (required)
    # Note: LIB_DIR already includes machine type (e.g., data/lib/arm64-darwin)
    lib_dir = os.environ.get('LIB_DIR')

    if not lib_dir:
        click.echo("ERROR: LIB_DIR environment variable not set", err=True)
        sys.exit(1)

    # Structure: lib/arm64-darwin/pip/venv (PipProvider will create venv automatically)
    pip_venv_path = Path(lib_dir) / 'pip' / 'venv'
    pip_venv_path.parent.mkdir(parents=True, exist_ok=True)
    venv_python = pip_venv_path / 'bin' / 'python'

    # Prefer a stable system python for venv creation if provided/available
    preferred_python = os.environ.get('PIP_VENV_PYTHON', '').strip()
    if not preferred_python:
        for candidate in ('python3.12', 'python3.11', 'python3.10'):
            if shutil.which(candidate):
                preferred_python = candidate
                break
    if preferred_python and not venv_python.exists():
        try:
            subprocess.run(
                [preferred_python, '-m', 'venv', str(pip_venv_path), '--upgrade-deps'],
                check=True,
            )
        except Exception:
            # Fall back to PipProvider-managed venv creation
            pass

    # Use abx-pkg PipProvider to install binary with custom venv
    provider = PipProvider(pip_venv=pip_venv_path)
    if not provider.INSTALLER_BIN:
        click.echo("pip not available on this system", err=True)
        sys.exit(1)

    click.echo(f"Installing {name} via pip to venv at {pip_venv_path}...", err=True)

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

    # Emit PATH update for pip bin dir
    pip_bin_dir = str(pip_venv_path / 'bin')
    current_path = os.environ.get('PATH', '')

    # Check if pip_bin_dir is already in PATH
    path_dirs = current_path.split(':')
    new_path = f"{pip_bin_dir}:{current_path}" if current_path else pip_bin_dir
    if pip_bin_dir in path_dirs:
        new_path = current_path
    print(json.dumps({
        'type': 'Machine',
        'config': {
            'PATH': new_path,
        },
    }))

    # Log human-readable info to stderr
    click.echo(f"Installed {name} at {binary.abspath}", err=True)
    click.echo(f"  version: {binary.version}", err=True)

    sys.exit(0)


if __name__ == '__main__':
    main()
