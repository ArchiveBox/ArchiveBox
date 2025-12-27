#!/usr/bin/env python3
"""
Install hook for forum-dl.

Runs at crawl start to verify forum-dl binary is available.
Outputs JSONL for InstalledBinary and Machine config updates.
Respects FORUMDL_BINARY env var for custom binary paths.
"""

import os
import sys
import json
from pathlib import Path


def find_forumdl() -> dict | None:
    """Find forum-dl binary, respecting FORUMDL_BINARY env var."""
    try:
        from abx_pkg import Binary, PipProvider, EnvProvider

        # Check if user has configured a custom binary
        configured_binary = os.environ.get('FORUMDL_BINARY', '').strip()

        if configured_binary:
            if '/' in configured_binary:
                bin_name = Path(configured_binary).name
            else:
                bin_name = configured_binary
        else:
            bin_name = 'forum-dl'

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
    configured_binary = os.environ.get('FORUMDL_BINARY', '').strip()
    if configured_binary and '/' in configured_binary:
        bin_name = Path(configured_binary).name
    elif configured_binary:
        bin_name = configured_binary
    else:
        bin_name = 'forum-dl'

    # Check for forum-dl (required)
    forumdl_result = find_forumdl()

    missing_deps = []

    # Emit results for forum-dl
    if forumdl_result and forumdl_result.get('abspath') and forumdl_result.get('version'):
        print(json.dumps({
            'type': 'InstalledBinary',
            'name': forumdl_result['name'],
            'abspath': forumdl_result['abspath'],
            'version': forumdl_result['version'],
            'sha256': forumdl_result['sha256'],
            'binprovider': forumdl_result['binprovider'],
        }))

        print(json.dumps({
            'type': 'Machine',
            '_method': 'update',
            'key': 'config/FORUMDL_BINARY',
            'value': forumdl_result['abspath'],
        }))

        if forumdl_result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/FORUMDL_VERSION',
                'value': forumdl_result['version'],
            }))
    else:
        # forum-dl has cchardet dependency that doesn't compile on Python 3.14+
        # Provide overrides to install with chardet instead
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': bin_name,
            'bin_providers': 'pip,env',
            'overrides': {
                'pip': {
                    'packages': ['--no-deps', 'forum-dl', 'chardet', 'pydantic', 'beautifulsoup4', 'lxml',
                                 'requests', 'urllib3', 'tenacity', 'python-dateutil',
                                 'html2text', 'warcio']
                }
            }
        }))
        missing_deps.append(bin_name)

    if missing_deps:
        print(f"Missing dependencies: {', '.join(missing_deps)}", file=sys.stderr)
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
