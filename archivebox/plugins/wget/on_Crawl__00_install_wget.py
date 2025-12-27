#!/usr/bin/env python3
"""
Install hook for wget binary.

Runs at crawl start to verify wget is available.
Outputs JSONL for InstalledBinary and Machine config updates.
Respects WGET_BINARY env var for custom binary paths.
"""

import os
import sys
import json
from pathlib import Path


def find_wget() -> dict | None:
    """Find wget binary using abx-pkg, respecting WGET_BINARY env var."""
    try:
        from abx_pkg import Binary, EnvProvider

        # Check if user has configured a custom binary
        configured_binary = os.environ.get('WGET_BINARY', '').strip()

        if configured_binary:
            # User specified a custom binary path or name
            if '/' in configured_binary:
                # Absolute path - extract name from path
                bin_name = Path(configured_binary).name
            else:
                # Just a binary name
                bin_name = configured_binary
        else:
            # Default to 'wget'
            bin_name = 'wget'

        binary = Binary(name=bin_name, binproviders=[EnvProvider()])
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
    """Find wget binary and output JSONL."""
    # Determine binary name from config
    configured_binary = os.environ.get('WGET_BINARY', '').strip()
    if configured_binary and '/' in configured_binary:
        bin_name = Path(configured_binary).name
    elif configured_binary:
        bin_name = configured_binary
    else:
        bin_name = 'wget'

    result = find_wget()

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
            'key': 'config/WGET_BINARY',
            'value': result['abspath'],
        }))

        if result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/WGET_VERSION',
                'value': result['version'],
            }))

        sys.exit(0)
    else:
        # Output Dependency request (uses configured bin_name)
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': bin_name,
            'bin_providers': 'apt,brew,env',
        }))

        # Exit non-zero to indicate binary not found
        print(f"{bin_name} binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
