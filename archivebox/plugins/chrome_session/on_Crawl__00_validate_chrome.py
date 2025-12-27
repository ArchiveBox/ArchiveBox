#!/usr/bin/env python3
"""
Validation hook for Chrome/Chromium binary.

Runs at crawl start to verify Chrome is available.
Outputs JSONL for InstalledBinary and Machine config updates.
"""

import sys
import json


def find_chrome() -> dict | None:
    """Find Chrome/Chromium binary."""
    try:
        from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider

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
