#!/usr/bin/env python3
"""
Validation hook for readability-extractor binary.

Runs at crawl start to verify readability-extractor is available.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import sys
import json


def find_readability() -> dict | None:
    """Find readability-extractor binary."""
    try:
        from abx_pkg import Binary, NpmProvider, EnvProvider

        binary = Binary(name='readability-extractor', binproviders=[NpmProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'readability-extractor',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception:
        pass

    return None


def main():
    result = find_readability()

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
            'key': 'config/READABILITY_BINARY',
            'value': result['abspath'],
        }))

        if result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/READABILITY_VERSION',
                'value': result['version'],
            }))

        sys.exit(0)
    else:
        # readability-extractor is installed from GitHub
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'readability-extractor',
            'bin_providers': 'npm,env',
            'overrides': {
                'npm': {'packages': ['github:ArchiveBox/readability-extractor']}
            }
        }))
        print(f"readability-extractor binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
