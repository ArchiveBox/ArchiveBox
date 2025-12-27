#!/usr/bin/env python3
"""
Validation hook for postlight-parser binary.

Runs at crawl start to verify postlight-parser is available.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import os
import sys
import json
import shutil
import hashlib
import subprocess
from pathlib import Path


def find_mercury() -> dict | None:
    """Find postlight-parser binary."""
    try:
        from abx_pkg import Binary, NpmProvider, EnvProvider

        binary = Binary(name='postlight-parser', binproviders=[NpmProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'postlight-parser',
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
    abspath = shutil.which('postlight-parser') or os.environ.get('MERCURY_BINARY', '')
    if abspath and Path(abspath).is_file():
        return {
            'name': 'postlight-parser',
            'abspath': abspath,
            'version': None,
            'sha256': None,
            'binprovider': 'env',
        }

    return None


def main():
    result = find_mercury()

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
            'key': 'config/MERCURY_BINARY',
            'value': result['abspath'],
        }))

        if result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/MERCURY_VERSION',
                'value': result['version'],
            }))

        sys.exit(0)
    else:
        # postlight-parser is installed as @postlight/parser in npm
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'postlight-parser',
            'bin_providers': 'npm,env',
            'overrides': {
                'npm': {'packages': ['@postlight/parser']}
            }
        }))
        print(f"postlight-parser binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
