#!/usr/bin/env python3
"""
Install hook for Chrome/Chromium and puppeteer-core.

Runs at crawl start to install/find Chromium and puppeteer-core.
Outputs JSONL for Binary and Machine config updates.
Respects CHROME_BINARY env var for custom binary paths.
Uses `npx @puppeteer/browsers install chromium@latest` and parses output.

NOTE: We use Chromium instead of Chrome because Chrome 137+ removed support for
--load-extension and --disable-extensions-except flags, which are needed for
loading unpacked extensions in headless mode.
"""

import os
import sys
import json
import subprocess
from pathlib import Path


def get_chrome_version(binary_path: str) -> str | None:
    """Get Chrome/Chromium version string."""
    try:
        result = subprocess.run(
            [binary_path, '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def install_puppeteer_core() -> bool:
    """Install puppeteer-core to NODE_MODULES_DIR if not present."""
    node_modules_dir = os.environ.get('NODE_MODULES_DIR', '').strip()
    if not node_modules_dir:
        # No isolated node_modules, skip (will use global)
        return True

    node_modules_path = Path(node_modules_dir)
    if (node_modules_path / 'puppeteer-core').exists():
        return True

    # Get npm prefix from NODE_MODULES_DIR (parent of node_modules)
    npm_prefix = node_modules_path.parent

    try:
        print(f"[*] Installing puppeteer-core to {npm_prefix}...", file=sys.stderr)
        result = subprocess.run(
            ['npm', 'install', '--prefix', str(npm_prefix), 'puppeteer-core', '@puppeteer/browsers'],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            print(f"[+] puppeteer-core installed", file=sys.stderr)
            return True
        else:
            print(f"[!] Failed to install puppeteer-core: {result.stderr}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[!] Failed to install puppeteer-core: {e}", file=sys.stderr)
        return False


def install_chromium() -> dict | None:
    """Install Chromium using @puppeteer/browsers and parse output for binary path.

    Output format: "chromium@<version> <path_to_binary>"
    e.g.: "chromium@1563294 /Users/x/.cache/puppeteer/chromium/.../Chromium"

    Note: npx is fast when chromium is already cached - it returns the path without re-downloading.
    """
    try:
        print("[*] Installing Chromium via @puppeteer/browsers...", file=sys.stderr)

        # Use --path to install to puppeteer's standard cache location
        cache_path = os.path.expanduser('~/.cache/puppeteer')

        result = subprocess.run(
            ['npx', '@puppeteer/browsers', 'install', 'chromium@1563297', f'--path={cache_path}'],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=300
        )

        if result.returncode != 0:
            print(f"[!] Failed to install Chromium: {result.stderr}", file=sys.stderr)
            return None

        # Parse output: "chromium@1563294 /path/to/Chromium"
        output = result.stdout.strip()
        parts = output.split(' ', 1)
        if len(parts) != 2:
            print(f"[!] Failed to parse install output: {output}", file=sys.stderr)
            return None

        version_str = parts[0]  # "chromium@1563294"
        binary_path = parts[1].strip()

        if not binary_path or not os.path.exists(binary_path):
            print(f"[!] Binary not found at: {binary_path}", file=sys.stderr)
            return None

        # Extract version number
        version = version_str.split('@')[1] if '@' in version_str else None

        print(f"[+] Chromium installed: {binary_path}", file=sys.stderr)

        return {
            'name': 'chromium',
            'abspath': binary_path,
            'version': version,
            'binprovider': 'puppeteer',
        }

    except subprocess.TimeoutExpired:
        print("[!] Chromium install timed out", file=sys.stderr)
    except FileNotFoundError:
        print("[!] npx not found - is Node.js installed?", file=sys.stderr)
    except Exception as e:
        print(f"[!] Failed to install Chromium: {e}", file=sys.stderr)

    return None


def main():
    # Install puppeteer-core if NODE_MODULES_DIR is set
    install_puppeteer_core()

    # Check if CHROME_BINARY is already set and valid
    configured_binary = os.environ.get('CHROME_BINARY', '').strip()
    if configured_binary and os.path.isfile(configured_binary) and os.access(configured_binary, os.X_OK):
        version = get_chrome_version(configured_binary)
        print(json.dumps({
            'type': 'Binary',
            'name': 'chromium',
            'abspath': configured_binary,
            'version': version,
            'binprovider': 'env',
        }))
        sys.exit(0)

    # Install/find Chromium via puppeteer
    result = install_chromium()

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
        print("Chromium binary not found", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
