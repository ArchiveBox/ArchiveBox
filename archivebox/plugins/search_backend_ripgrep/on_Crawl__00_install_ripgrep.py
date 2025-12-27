#!/usr/bin/env python3
"""
Install hook for ripgrep binary.

Only runs if SEARCH_BACKEND_ENGINE is set to 'ripgrep'.
Outputs JSONL for InstalledBinary and Machine config updates.
Respects RIPGREP_BINARY env var for custom binary paths.
"""

import os
import sys
import json
from pathlib import Path


def find_ripgrep() -> dict | None:
    """Find ripgrep binary, respecting RIPGREP_BINARY env var."""
    try:
        from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider

        # Check if user has configured a custom binary
        configured_binary = os.environ.get('RIPGREP_BINARY', '').strip()

        if configured_binary:
            if '/' in configured_binary:
                bin_name = Path(configured_binary).name
            else:
                bin_name = configured_binary
        else:
            bin_name = 'rg'

        binary = Binary(name=bin_name, binproviders=[AptProvider(), BrewProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': bin_name,
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception:
        pass

    return None


def main():
    """Find ripgrep binary and output JSONL."""

    # Check if ripgrep search backend is enabled
    search_backend = os.environ.get('SEARCH_BACKEND_ENGINE', '').lower()

    if search_backend != 'ripgrep':
        # No-op: ripgrep is not the active search backend
        sys.exit(0)

    # Determine binary name from config
    configured_binary = os.environ.get('RIPGREP_BINARY', '').strip()
    if configured_binary and '/' in configured_binary:
        bin_name = Path(configured_binary).name
    elif configured_binary:
        bin_name = configured_binary
    else:
        bin_name = 'rg'

    result = find_ripgrep()

    if result and result.get('abspath'):
        # Output InstalledBinary
        print(json.dumps({
            'type': 'InstalledBinary',
            'name': result['name'],
            'abspath': result['abspath'],
            'version': result['version'],
            'sha256': result['sha256'],
            'binprovider': result['binprovider'],
        }))

        # Output Machine config update
        print(json.dumps({
            'type': 'Machine',
            '_method': 'update',
            'key': 'config/RIPGREP_BINARY',
            'value': result['abspath'],
        }))

        if result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/RIPGREP_VERSION',
                'value': result['version'],
            }))

        sys.exit(0)
    else:
        # Output Dependency request
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': bin_name,
            'bin_providers': 'apt,brew,cargo,env',
        }))

        # Exit non-zero to indicate binary not found
        print(f"{bin_name} binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
