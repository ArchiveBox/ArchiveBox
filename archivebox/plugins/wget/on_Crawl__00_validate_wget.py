#!/usr/bin/env python3
"""
Validation hook for wget binary.

Runs at crawl start to verify wget is available.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import sys
import json


def find_wget() -> dict | None:
    """Find wget binary using abx-pkg."""
    try:
        from abx_pkg import Binary, EnvProvider

        binary = Binary(name='wget', binproviders=[EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'wget',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception:
        pass

    return None


def main():
    """Validate wget binary and output JSONL."""

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
        # Output Dependency request
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'wget',
            'bin_providers': 'apt,brew,env',
        }))

        # Exit non-zero to indicate binary not found
        print(f"wget binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
