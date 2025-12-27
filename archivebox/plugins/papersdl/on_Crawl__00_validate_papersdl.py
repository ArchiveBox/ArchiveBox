#!/usr/bin/env python3
"""
Validation hook for papers-dl.

Runs at crawl start to verify papers-dl binary is available.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import sys
import json


def find_papersdl() -> dict | None:
    """Find papers-dl binary."""
    try:
        from abx_pkg import Binary, PipProvider, EnvProvider

        binary = Binary(name='papers-dl', binproviders=[PipProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'papers-dl',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception:
        pass

    return None


def main():
    # Check for papers-dl (required)
    papersdl_result = find_papersdl()

    missing_deps = []

    # Emit results for papers-dl
    if papersdl_result and papersdl_result.get('abspath'):
        print(json.dumps({
            'type': 'InstalledBinary',
            'name': papersdl_result['name'],
            'abspath': papersdl_result['abspath'],
            'version': papersdl_result['version'],
            'sha256': papersdl_result['sha256'],
            'binprovider': papersdl_result['binprovider'],
        }))

        print(json.dumps({
            'type': 'Machine',
            '_method': 'update',
            'key': 'config/PAPERSDL_BINARY',
            'value': papersdl_result['abspath'],
        }))

        if papersdl_result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/PAPERSDL_VERSION',
                'value': papersdl_result['version'],
            }))
    else:
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'papers-dl',
            'bin_providers': 'pip,env',
        }))
        missing_deps.append('papers-dl')

    if missing_deps:
        print(f"Missing dependencies: {', '.join(missing_deps)}", file=sys.stderr)
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
