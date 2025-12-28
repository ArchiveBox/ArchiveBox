#!/usr/bin/env python3
"""
Install hook for Chrome/Chromium binary.

Runs at crawl start to verify Chrome is available.
Outputs JSONL for Binary and Machine config updates.
Respects CHROME_BINARY env var for custom binary paths.
Falls back to `npx @puppeteer/browsers install chrome@stable` if not found.
"""

import os
import sys
import json
import subprocess


def install_chrome_via_puppeteer() -> bool:
    """Install Chrome using @puppeteer/browsers."""
    try:
        print("Chrome not found, attempting to install via @puppeteer/browsers...", file=sys.stderr)
        result = subprocess.run(
            ['npx', '@puppeteer/browsers', 'install', 'chrome@stable'],
            capture_output=True,
            text=True,
            timeout=300
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        print(f"Failed to install Chrome: {e}", file=sys.stderr)
        return False


def find_chrome() -> dict | None:
    """Find Chrome/Chromium binary, respecting CHROME_BINARY env var."""
    # Quick check: if CHROME_BINARY is set and exists, skip expensive lookup
    configured_binary = os.environ.get('CHROME_BINARY', '').strip()
    if configured_binary and os.path.isfile(configured_binary) and os.access(configured_binary, os.X_OK):
        # Binary is already configured and valid - exit immediately
        sys.exit(0)

    try:
        from abx_pkg import Binary, NpmProvider, EnvProvider, BrewProvider, AptProvider

        # Try to find chrome using abx-pkg
        binary = Binary(
            name='chrome',
            binproviders=[NpmProvider(), EnvProvider(), BrewProvider(), AptProvider()],
            overrides={'npm': {'packages': ['@puppeteer/browsers']}}
        )

        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'chrome',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }

        # If not found, try to install via @puppeteer/browsers
        if install_chrome_via_puppeteer():
            # Try loading again after install
            loaded = binary.load()
            if loaded and loaded.abspath:
                return {
                    'name': 'chrome',
                    'abspath': str(loaded.abspath),
                    'version': str(loaded.version) if loaded.version else None,
                    'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                    'binprovider': loaded.binprovider.name if loaded.binprovider else 'npm',
                }
    except Exception:
        pass

    return None


def main():
    result = find_chrome()

    if result and result.get('abspath'):
        print(json.dumps({
            'type': 'Binary',
            'name': result['name'],
            'abspath': result['abspath'],
            'version': result['version'],
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
        print(f"Chrome/Chromium binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
