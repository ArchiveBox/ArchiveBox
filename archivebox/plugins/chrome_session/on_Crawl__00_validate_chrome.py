#!/usr/bin/env python3
"""
Validation hook for Chrome/Chromium binary.

Runs at crawl start to verify Chrome is available.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import os
import sys
import json
import shutil
import hashlib
import subprocess
from pathlib import Path


# Common Chrome/Chromium binary names and paths
CHROME_NAMES = [
    'chromium',
    'chromium-browser',
    'google-chrome',
    'google-chrome-stable',
    'chrome',
]

CHROME_PATHS = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/snap/bin/chromium',
    '/opt/google/chrome/chrome',
]


def get_binary_version(abspath: str) -> str | None:
    """Get version string from Chrome binary."""
    try:
        result = subprocess.run(
            [abspath, '--version'],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            # Chrome version string: "Google Chrome 120.0.6099.109" or "Chromium 120.0.6099.109"
            first_line = result.stdout.strip().split('\n')[0]
            parts = first_line.split()
            # Find version number (looks like 120.0.6099.109)
            for part in parts:
                if '.' in part and part[0].isdigit():
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


def find_chrome() -> dict | None:
    """Find Chrome/Chromium binary."""
    # Check env var first
    env_path = os.environ.get('CHROME_BINARY', '')
    if env_path and Path(env_path).is_file():
        return {
            'name': 'chrome',
            'abspath': env_path,
            'version': get_binary_version(env_path),
            'sha256': get_binary_hash(env_path),
            'binprovider': 'env',
        }

    # Try shutil.which for various names
    for name in CHROME_NAMES:
        abspath = shutil.which(name)
        if abspath:
            return {
                'name': 'chrome',
                'abspath': abspath,
                'version': get_binary_version(abspath),
                'sha256': get_binary_hash(abspath),
                'binprovider': 'env',
            }

    # Check common paths
    for path in CHROME_PATHS:
        if Path(path).is_file():
            return {
                'name': 'chrome',
                'abspath': path,
                'version': get_binary_version(path),
                'sha256': get_binary_hash(path),
                'binprovider': 'env',
            }

    return None


def main():
    result = find_chrome()

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
            'key': 'config/CHROME_BINARY',
            'value': result['abspath'],
        }))

        if result['version']:
            print(json.dumps({
                'type': 'Machine',
                '_method': 'update',
                'key': 'config/CHROME_VERSION',
                'value': result['version'],
            }))

        sys.exit(0)
    else:
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'chrome',
            'bin_providers': 'apt,brew,env',
        }))
        print(f"Chrome/Chromium binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
