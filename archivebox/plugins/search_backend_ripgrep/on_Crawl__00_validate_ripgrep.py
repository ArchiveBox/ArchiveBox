#!/usr/bin/env python3
"""
Validation hook for ripgrep binary.

Only runs if SEARCH_BACKEND_ENGINE is set to 'ripgrep'.
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
    """Get version string from ripgrep binary."""
    try:
        result = subprocess.run(
            [abspath, '--version'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout:
            # ripgrep version string: "ripgrep 14.1.0"
            first_line = result.stdout.strip().split('\n')[0]
            parts = first_line.split()
            for i, part in enumerate(parts):
                if part.lower() == 'ripgrep' and i + 1 < len(parts):
                    return parts[i + 1]
            # Try to find version number pattern
            for part in parts:
                if part[0].isdigit() and '.' in part:
                    return part
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


def find_ripgrep() -> dict | None:
    """Find ripgrep binary using shutil.which or env var."""
    # Check env var first - if it's an absolute path and exists, use it
    ripgrep_env = os.environ.get('RIPGREP_BINARY', '')
    if ripgrep_env and '/' in ripgrep_env and Path(ripgrep_env).is_file():
        abspath = ripgrep_env
    else:
        # Otherwise try shutil.which with the env var as the binary name
        abspath = shutil.which(ripgrep_env) if ripgrep_env else None
        if not abspath:
            abspath = shutil.which('rg')

    if abspath and Path(abspath).is_file():
        return {
            'name': 'rg',
            'abspath': abspath,
            'version': get_binary_version(abspath),
            'sha256': get_binary_hash(abspath),
            'binprovider': 'env',
        }

    return None


def main():
    """Validate ripgrep binary and output JSONL."""

    # Check if ripgrep search backend is enabled
    search_backend = os.environ.get('SEARCH_BACKEND_ENGINE', '').lower()

    if search_backend != 'ripgrep':
        # No-op: ripgrep is not the active search backend
        sys.exit(0)

    result = find_ripgrep()

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
            'key': 'config/RIPGREP_BINARY',
            'value': result['abspath'],
        }))

        if result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/RIPGREP_VERSION',
                'value': result['version'],
            }))

        sys.exit(0)
    else:
        # Output Dependency request
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'rg',
            'bin_providers': 'apt,brew,cargo,env',
        }))

        # Exit non-zero to indicate binary not found
        print(f"ripgrep binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
