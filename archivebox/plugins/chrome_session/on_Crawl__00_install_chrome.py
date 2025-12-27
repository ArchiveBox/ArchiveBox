#!/usr/bin/env python3
"""
Install hook for Chrome/Chromium binary.

Runs at crawl start to verify Chrome is available.
Outputs JSONL for InstalledBinary and Machine config updates.
Respects CHROME_BINARY env var for custom binary paths.
"""

import os
import sys
import json
from pathlib import Path


def find_chrome() -> dict | None:
    """Find Chrome/Chromium binary, respecting CHROME_BINARY env var."""
    try:
        from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider

        # Check if user has configured a custom binary
        configured_binary = os.environ.get('CHROME_BINARY', '').strip()

        if configured_binary:
            # User specified a custom binary path or name
            if '/' in configured_binary:
                bin_name = Path(configured_binary).name
            else:
                bin_name = configured_binary

            binary = Binary(name=bin_name, binproviders=[EnvProvider()])
            loaded = binary.load()
            if loaded and loaded.abspath:
                return {
                    'name': 'chrome',
                    'abspath': str(loaded.abspath),
                    'version': str(loaded.version) if loaded.version else None,
                    'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                    'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
                }
        else:
            # Try common Chrome/Chromium binary names
            for name in ['google-chrome', 'chromium', 'chromium-browser', 'google-chrome-stable', 'chrome']:
                binary = Binary(name=name, binproviders=[AptProvider(), BrewProvider(), EnvProvider()])
                loaded = binary.load()
                if loaded and loaded.abspath:
                    return {
                        'name': 'chrome',
                        'abspath': str(loaded.abspath),
                        'version': str(loaded.version) if loaded.version else None,
                        'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                        'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
                    }
    except Exception:
        pass

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
