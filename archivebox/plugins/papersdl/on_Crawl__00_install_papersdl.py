#!/usr/bin/env python3
"""
Install hook for papers-dl.

Runs at crawl start to verify papers-dl binary is available.
Outputs JSONL for InstalledBinary and Machine config updates.
Respects PAPERSDL_BINARY env var for custom binary paths.
"""

import os
import sys
import json
from pathlib import Path


def find_papersdl() -> dict | None:
    """Find papers-dl binary, respecting PAPERSDL_BINARY env var."""
    try:
        from abx_pkg import Binary, PipProvider, EnvProvider

        # Check if user has configured a custom binary
        configured_binary = os.environ.get('PAPERSDL_BINARY', '').strip()

        if configured_binary:
            if '/' in configured_binary:
                bin_name = Path(configured_binary).name
            else:
                bin_name = configured_binary
        else:
            bin_name = 'papers-dl'

        binary = Binary(name=bin_name, binproviders=[PipProvider(), EnvProvider()])
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
    configured_binary = os.environ.get('PAPERSDL_BINARY', '').strip()
    if configured_binary and '/' in configured_binary:
        bin_name = Path(configured_binary).name
    elif configured_binary:
        bin_name = configured_binary
    else:
        bin_name = 'papers-dl'

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
            'bin_name': bin_name,
            'bin_providers': 'pip,env',
        }))
        missing_deps.append(bin_name)

    if missing_deps:
        print(f"Missing dependencies: {', '.join(missing_deps)}", file=sys.stderr)
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
