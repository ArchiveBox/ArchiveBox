#!/usr/bin/env python3
"""
Install hook for single-file binary.

Runs at crawl start to verify single-file (npm package) is available.
Outputs JSONL for InstalledBinary and Machine config updates.
Respects SINGLEFILE_BINARY env var for custom binary paths.
"""

import os
import sys
import json
from pathlib import Path


def find_singlefile() -> dict | None:
    """Find single-file binary, respecting SINGLEFILE_BINARY env var."""
    try:
        from abx_pkg import Binary, NpmProvider, EnvProvider

        # Check if user has configured a custom binary
        configured_binary = os.environ.get('SINGLEFILE_BINARY', '').strip()

        if configured_binary:
            if '/' in configured_binary:
                bin_name = Path(configured_binary).name
            else:
                bin_name = configured_binary
        else:
            bin_name = 'single-file'

        binary = Binary(name=bin_name, binproviders=[NpmProvider(), EnvProvider()])
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
    # Determine binary name from config
    configured_binary = os.environ.get('SINGLEFILE_BINARY', '').strip()
    if configured_binary and '/' in configured_binary:
        bin_name = Path(configured_binary).name
    elif configured_binary:
        bin_name = configured_binary
    else:
        bin_name = 'single-file'

    result = find_singlefile()

    if result and result.get('abspath'):
        print(json.dumps({
            'type': 'InstalledBinary',
            'name': result['name'],
            'abspath': result['abspath'],
            'version': result['version'],
            'sha256': result['sha256'],
            'binprovider': result['binprovider'],
        }))

        print(json.dumps({
            'type': 'Machine',
            '_method': 'update',
            'key': 'config/SINGLEFILE_BINARY',
            'value': result['abspath'],
        }))

        if result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/SINGLEFILE_VERSION',
                'value': result['version'],
            }))

        sys.exit(0)
    else:
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': bin_name,
            'bin_providers': 'npm,env',
        }))
        print(f"{bin_name} binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
