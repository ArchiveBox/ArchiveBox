#!/usr/bin/env python3
"""
Validation hook for gallery-dl.

Runs at crawl start to verify gallery-dl binary is available.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import sys
import json


def find_gallerydl() -> dict | None:
    """Find gallery-dl binary."""
    try:
        from abx_pkg import Binary, PipProvider, EnvProvider

        binary = Binary(name='gallery-dl', binproviders=[PipProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'gallery-dl',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception:
        pass

    return None


def main():
    # Check for gallery-dl (required)
    gallerydl_result = find_gallerydl()

    missing_deps = []

    # Emit results for gallery-dl
    if gallerydl_result and gallerydl_result.get('abspath'):
        print(json.dumps({
            'type': 'InstalledBinary',
            'name': gallerydl_result['name'],
            'abspath': gallerydl_result['abspath'],
            'version': gallerydl_result['version'],
            'sha256': gallerydl_result['sha256'],
            'binprovider': gallerydl_result['binprovider'],
        }))

        print(json.dumps({
            'type': 'Machine',
            '_method': 'update',
            'key': 'config/GALLERYDL_BINARY',
            'value': gallerydl_result['abspath'],
        }))

        if gallerydl_result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/GALLERYDL_VERSION',
                'value': gallerydl_result['version'],
            }))
    else:
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'gallery-dl',
            'bin_providers': 'pip,env',
        }))
        missing_deps.append('gallery-dl')

    if missing_deps:
        print(f"Missing dependencies: {', '.join(missing_deps)}", file=sys.stderr)
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
