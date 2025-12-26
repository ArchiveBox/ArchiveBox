#!/usr/bin/env python3
"""
Validation hook for gallery-dl.

Runs at crawl start to verify gallery-dl binary is available.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import os
import sys
import json
import shutil
import hashlib
import subprocess
from pathlib import Path


def get_binary_version(abspath: str, version_flag: str = '--version') -> str | None:
    """Get version string from binary."""
    try:
        result = subprocess.run(
            [abspath, version_flag],
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


def find_gallerydl() -> dict | None:
    """Find gallery-dl binary."""
    try:
        from abx_pkg import Binary, PipProvider, EnvProvider

        class GalleryDlBinary(Binary):
            name: str = 'gallery-dl'
            binproviders_supported = [PipProvider(), EnvProvider()]

        binary = GalleryDlBinary()
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'gallery-dl',
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
    abspath = shutil.which('gallery-dl') or os.environ.get('GALLERY_DL_BINARY', '')
    if abspath and Path(abspath).is_file():
        return {
            'name': 'gallery-dl',
            'abspath': abspath,
            'version': get_binary_version(abspath),
            'sha256': get_binary_hash(abspath),
            'binprovider': 'env',
        }

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
            'key': 'config/GALLERY_DL_BINARY',
            'value': gallerydl_result['abspath'],
        }))

        if gallerydl_result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/GALLERY_DL_VERSION',
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
