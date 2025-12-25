#!/usr/bin/env python3
"""
Validation hook for wget binary.

Runs at crawl start to verify wget is available.
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
            # wget version string: "GNU Wget 1.24.5 built on ..."
            first_line = result.stdout.strip().split('\n')[0]
            # Extract version number
            parts = first_line.split()
            for i, part in enumerate(parts):
                if part.lower() == 'wget' and i + 1 < len(parts):
                    return parts[i + 1]
            return first_line[:32]
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


def find_wget() -> dict | None:
    """Find wget binary using abx-pkg or fallback to shutil.which."""
    # Try abx-pkg first
    try:
        from abx_pkg import Binary, EnvProvider

        class WgetBinary(Binary):
            name: str = 'wget'
            binproviders_supported = [EnvProvider()]

        binary = WgetBinary()
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'wget',
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
    abspath = shutil.which('wget') or os.environ.get('WGET_BINARY', '')
    if abspath and Path(abspath).is_file():
        return {
            'name': 'wget',
            'abspath': abspath,
            'version': get_binary_version(abspath),
            'sha256': get_binary_hash(abspath),
            'binprovider': 'env',
        }

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
