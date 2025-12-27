#!/usr/bin/env python3
"""
Validation hook for ripgrep binary.

Only runs if SEARCH_BACKEND_ENGINE is set to 'ripgrep'.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import os
import sys
import json


def find_ripgrep() -> dict | None:
    """Find ripgrep binary."""
    try:
        from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider

        binary = Binary(name='rg', binproviders=[AptProvider(), BrewProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'rg',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception:
        pass

    return None


def main():
    """Validate ripgrep binary and output JSONL."""

    # Check if ripgrep search backend is enabled
    search_backend = os.environ.get('SEARCH_BACKEND_ENGINE', '').lower()

    if search_backend != 'ripgrep':
        # No-op: ripgrep is not the active search backend
        sys.exit(0)

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
            'bin_name': 'rg',
            'bin_providers': 'apt,brew,cargo,env',
        }))

        # Exit non-zero to indicate binary not found
        print(f"ripgrep binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
