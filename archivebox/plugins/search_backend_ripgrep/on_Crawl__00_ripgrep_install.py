#!/usr/bin/env python3
"""
Install hook for ripgrep binary.

Runs at crawl start to verify ripgrep is available when SEARCH_BACKEND_ENGINE='ripgrep'.
Outputs JSONL for Binary and Machine config updates.
Uses abx-pkg to handle installation via apt/brew providers.
"""

import os
import sys
import json


def find_ripgrep() -> dict | None:
    """Find ripgrep binary using abx-pkg, respecting RIPGREP_BINARY env var."""
    # Quick check: if RIPGREP_BINARY is set and exists, skip expensive lookup
    configured_binary = os.environ.get('RIPGREP_BINARY', '').strip()
    if configured_binary and os.path.isfile(configured_binary) and os.access(configured_binary, os.X_OK):
        # Binary is already configured and valid - exit immediately
        sys.exit(0)

    try:
        from abx_pkg import Binary, EnvProvider, AptProvider, BrewProvider, BinProviderOverrides

        # Try to find ripgrep using abx-pkg (EnvProvider checks PATH, apt/brew handle installation)
        binary = Binary(
            name='rg',
            binproviders=[EnvProvider(), AptProvider(), BrewProvider()],
            overrides={
                'apt': {'packages': ['ripgrep']},
                'brew': {'packages': ['ripgrep']},
            }
        )

        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'rg',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception as e:
        print(f"Error loading ripgrep: {e}", file=sys.stderr)
        pass

    return None


def main():
    # Only proceed if ripgrep backend is enabled
    search_backend_engine = os.environ.get('SEARCH_BACKEND_ENGINE', 'ripgrep').strip()
    if search_backend_engine != 'ripgrep':
        # Not using ripgrep, exit successfully without output
        sys.exit(0)

    result = find_ripgrep()

    if result and result.get('abspath'):
        print(json.dumps({
            'type': 'Binary',
            'name': result['name'],
            'abspath': result['abspath'],
            'version': result['version'],
            'binprovider': result['binprovider'],
        }))

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
        print(f"Ripgrep binary not found (install with: apt install ripgrep or brew install ripgrep)", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
