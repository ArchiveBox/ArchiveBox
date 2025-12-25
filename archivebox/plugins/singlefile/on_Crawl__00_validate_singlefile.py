#!/usr/bin/env python3
"""
Validation hook for single-file binary.

Runs at crawl start to verify single-file (npm package) is available.
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
    """Get version string from single-file binary."""
    try:
        result = subprocess.run(
            [abspath, '--version'],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.strip().split('\n')[0][:32]
    except Exception:
        pass
    return None


def get_binary_hash(abspath: str) -> str | None:
    """Get SHA256 hash of binary."""
    try:
        # For scripts, hash the script content
        with open(abspath, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def find_singlefile() -> dict | None:
    """Find single-file binary."""
    # Check env var first
    env_path = os.environ.get('SINGLEFILE_BINARY', '')
    if env_path and Path(env_path).is_file():
        return {
            'name': 'single-file',
            'abspath': env_path,
            'version': get_binary_version(env_path),
            'sha256': get_binary_hash(env_path),
            'binprovider': 'env',
        }

    # Try shutil.which
    for name in ['single-file', 'singlefile']:
        abspath = shutil.which(name)
        if abspath:
            return {
                'name': 'single-file',
                'abspath': abspath,
                'version': get_binary_version(abspath),
                'sha256': get_binary_hash(abspath),
                'binprovider': 'npm',
            }

    # Check common npm paths
    npm_paths = [
        Path.home() / '.npm-global/bin/single-file',
        Path.home() / 'node_modules/.bin/single-file',
        Path('/usr/local/bin/single-file'),
        Path('/usr/local/lib/node_modules/.bin/single-file'),
    ]
    for path in npm_paths:
        if path.is_file():
            return {
                'name': 'single-file',
                'abspath': str(path),
                'version': get_binary_version(str(path)),
                'sha256': get_binary_hash(str(path)),
                'binprovider': 'npm',
            }

    return None


def main():
    result = find_singlefile()

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
            'key': 'config/SINGLEFILE_BINARY',
            'value': result['abspath'],
        }))

        if result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/SINGLEFILE_VERSION',
                'value': result['version'],
            }))

        sys.exit(0)
    else:
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'single-file',
            'bin_providers': 'npm,env',
        }))
        print(f"single-file binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
