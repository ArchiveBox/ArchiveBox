#!/usr/bin/env python3
"""
Install hook for Chrome/Chromium binary.

Runs at crawl start to verify Chromium is available.
Outputs JSONL for Binary and Machine config updates.
Respects CHROME_BINARY env var for custom binary paths.
Falls back to `npx @puppeteer/browsers install chromium@latest` if not found.

NOTE: We use Chromium instead of Chrome because Chrome 137+ removed support for
--load-extension and --disable-extensions-except flags, which are needed for
loading unpacked extensions in headless mode.
"""

import os
import sys
import json
import subprocess


def install_chromium_via_puppeteer() -> bool:
    """Install Chromium using @puppeteer/browsers."""
    try:
        print("Chromium not found, attempting to install via @puppeteer/browsers...", file=sys.stderr)
        result = subprocess.run(
            ['npx', '@puppeteer/browsers', 'install', 'chromium@latest'],
            capture_output=True,
            text=True,
            timeout=300
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        print(f"Failed to install Chromium: {e}", file=sys.stderr)
        return False


def find_chromium() -> dict | None:
    """Find Chromium binary, respecting CHROME_BINARY env var."""
    # Quick check: if CHROME_BINARY is set and exists, skip expensive lookup
    configured_binary = os.environ.get('CHROME_BINARY', '').strip()
    if configured_binary and os.path.isfile(configured_binary) and os.access(configured_binary, os.X_OK):
        # Binary is already configured and valid - exit immediately
        sys.exit(0)

    try:
        from abx_pkg import Binary, NpmProvider, EnvProvider, BrewProvider, AptProvider

        # Try to find chromium using abx-pkg
        # Prefer chromium over chrome because Chrome 137+ removed --load-extension support
        binary = Binary(
            name='chromium',
            binproviders=[NpmProvider(), EnvProvider(), BrewProvider(), AptProvider()],
            overrides={'npm': {'packages': ['@puppeteer/browsers']}}
        )

        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'chromium',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }

        # If not found, try to install via @puppeteer/browsers
        if install_chromium_via_puppeteer():
            # Try loading again after install
            loaded = binary.load()
            if loaded and loaded.abspath:
                return {
                    'name': 'chromium',
                    'abspath': str(loaded.abspath),
                    'version': str(loaded.version) if loaded.version else None,
                    'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                    'binprovider': loaded.binprovider.name if loaded.binprovider else 'npm',
                }
    except Exception:
        pass

    return None


def main():
    result = find_chromium()

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
                'key': 'config/CHROMIUM_VERSION',
                'value': result['version'],
            }))

        sys.exit(0)
    else:
        print(f"Chromium binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
