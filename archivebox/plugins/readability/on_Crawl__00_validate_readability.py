#!/usr/bin/env python3
"""
Validation hook for readability-extractor binary.

Runs at crawl start to verify readability-extractor is available.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import os
import sys
import json
import shutil
import hashlib
import subprocess
from pathlib import Path


def get_binary_version(abspath: str) -> str | None:
    """Get version string from binary."""
    try:
        result = subprocess.run(
            [abspath, '--version'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout:
            first_line = result.stdout.strip().split('\n')[0]
            return first_line[:64]
    except Exception:
        pass
    return None


def get_binary_hash(abspath: str) -> str | None:
    """Get SHA256 hash of binary."""
    try:
        with open(abspath, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def find_readability() -> dict | None:
    """Find readability-extractor binary."""
    try:
        from abx_pkg import Binary, NpmProvider, EnvProvider

        class ReadabilityBinary(Binary):
            name: str = 'readability-extractor'
            binproviders_supported = [NpmProvider(), EnvProvider()]
            overrides: dict = {'npm': {'packages': ['github:ArchiveBox/readability-extractor']}}

        binary = ReadabilityBinary()
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'readability-extractor',
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
    abspath = shutil.which('readability-extractor') or os.environ.get('READABILITY_BINARY', '')
    if abspath and Path(abspath).is_file():
        return {
            'name': 'readability-extractor',
            'abspath': abspath,
            'version': get_binary_version(abspath),
            'sha256': get_binary_hash(abspath),
            'binprovider': 'env',
        }

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
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'readability-extractor',
            'bin_providers': 'npm,env',
        }))
        print(f"readability-extractor binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
