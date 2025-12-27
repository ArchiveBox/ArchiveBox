#!/usr/bin/env python3
"""
Validation hook for forum-dl.

Runs at crawl start to verify forum-dl binary is available.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import os
import sys
import json
import shutil
import hashlib
import subprocess
from pathlib import Path


def find_forumdl() -> dict | None:
    """Find forum-dl binary."""
    try:
        from abx_pkg import Binary, PipProvider, EnvProvider

        binary = Binary(name='forum-dl', binproviders=[PipProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'forum-dl',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback to shutil.which
    abspath = shutil.which('forum-dl') or os.environ.get('FORUMDL_BINARY', '')
    if abspath and Path(abspath).is_file():
        return {
            'name': 'forum-dl',
            'abspath': abspath,
            'version': get_binary_version(abspath),
            'sha256': get_binary_hash(abspath),
            'binprovider': 'env',
        }

    return None


def main():
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
            'bin_name': 'forum-dl',
            'bin_providers': 'pip,env',
            'overrides': {
                'pip': {
                    'packages': ['--no-deps', 'forum-dl', 'chardet', 'pydantic', 'beautifulsoup4', 'lxml',
                                 'requests', 'urllib3', 'tenacity', 'python-dateutil',
                                 'html2text', 'warcio']
                }
            }
        }))
        missing_deps.append('forum-dl')

    if missing_deps:
        print(f"Missing dependencies: {', '.join(missing_deps)}", file=sys.stderr)
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
