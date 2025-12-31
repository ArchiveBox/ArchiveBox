#!/usr/bin/env python3
"""
Validate and compute derived Chrome config values.

This hook runs early in the Crawl lifecycle to:
1. Auto-detect Chrome binary location
2. Compute sandbox settings based on Docker detection
3. Validate binary availability and version
4. Set computed env vars for subsequent hooks

Output:
    - COMPUTED:KEY=VALUE lines that hooks.py parses and adds to env
    - Binary JSONL records to stdout when binaries are found
"""

import json
import os
import sys

from abx_pkg import Binary, EnvProvider


# Chrome binary search order
CHROME_BINARY_NAMES = [
    'chromium',
    'chromium-browser',
    'google-chrome',
    'google-chrome-stable',
    'chrome',
]

def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()

def get_env_bool(name: str, default: bool = False) -> bool:
    val = get_env(name, '').lower()
    if val in ('true', '1', 'yes', 'on'):
        return True
    if val in ('false', '0', 'no', 'off'):
        return False
    return default


def detect_docker() -> bool:
    """Detect if running inside Docker container."""
    return (
        os.path.exists('/.dockerenv') or
        os.environ.get('IN_DOCKER', '').lower() in ('true', '1', 'yes') or
        os.path.exists('/run/.containerenv')
    )


def find_chrome_binary(configured: str, provider: EnvProvider) -> Binary | None:
    """Find Chrome binary using abx-pkg, checking configured path first."""
    # Try configured binary first
    if configured:
        try:
            binary = Binary(name=configured, binproviders=[provider]).load()
            if binary.abspath:
                return binary
        except Exception:
            pass

    # Search common names
    for name in CHROME_BINARY_NAMES:
        try:
            binary = Binary(name=name, binproviders=[provider]).load()
            if binary.abspath:
                return binary
        except Exception:
            continue

    return None


def output_binary(binary: Binary, name: str):
    """Output Binary JSONL record to stdout."""
    machine_id = os.environ.get('MACHINE_ID', '')

    record = {
        'type': 'Binary',
        'name': name,
        'abspath': str(binary.abspath),
        'version': str(binary.version) if binary.version else '',
        'sha256': binary.sha256 or '',
        'binprovider': 'env',
        'machine_id': machine_id,
    }
    print(json.dumps(record))


def main():
    warnings = []
    errors = []
    computed = {}

    # Get config values
    chrome_binary = get_env('CHROME_BINARY', 'chromium')
    chrome_sandbox = get_env_bool('CHROME_SANDBOX', True)
    screenshot_enabled = get_env_bool('SCREENSHOT_ENABLED', True)
    pdf_enabled = get_env_bool('PDF_ENABLED', True)
    dom_enabled = get_env_bool('DOM_ENABLED', True)

    # Compute USE_CHROME (derived from extractor enabled flags)
    use_chrome = screenshot_enabled or pdf_enabled or dom_enabled
    computed['USE_CHROME'] = str(use_chrome).lower()

    # Detect Docker and adjust sandbox
    in_docker = detect_docker()
    computed['IN_DOCKER'] = str(in_docker).lower()

    if in_docker and chrome_sandbox:
        warnings.append(
            "Running in Docker with CHROME_SANDBOX=true. "
            "Chrome may fail to start. Consider setting CHROME_SANDBOX=false."
        )
        # Auto-disable sandbox in Docker unless explicitly set
        if not get_env('CHROME_SANDBOX'):
            computed['CHROME_SANDBOX'] = 'false'

    # Find Chrome binary using abx-pkg
    provider = EnvProvider()
    if use_chrome:
        chrome = find_chrome_binary(chrome_binary, provider)
        if not chrome or not chrome.abspath:
            errors.append(
                f"Chrome binary not found (tried: {chrome_binary}). "
                "Install Chrome/Chromium or set CHROME_BINARY path."
            )
            computed['CHROME_BINARY'] = ''
        else:
            computed['CHROME_BINARY'] = str(chrome.abspath)
            computed['CHROME_VERSION'] = str(chrome.version) if chrome.version else 'unknown'

            # Output Binary JSONL record for Chrome
            output_binary(chrome, name='chrome')

    # Check Node.js for Puppeteer
    node_binary_name = get_env('NODE_BINARY', 'node')
    try:
        node = Binary(name=node_binary_name, binproviders=[provider]).load()
        node_path = str(node.abspath) if node.abspath else ''
    except Exception:
        node = None
        node_path = ''

    if use_chrome and not node_path:
        errors.append(
            f"Node.js not found (tried: {node_binary_name}). "
            "Install Node.js or set NODE_BINARY path for Puppeteer."
        )
    else:
        computed['NODE_BINARY'] = node_path
        if node and node.abspath:
            # Output Binary JSONL record for Node
            output_binary(node, name='node')

    # Output computed values
    for key, value in computed.items():
        print(f"COMPUTED:{key}={value}")

    for warning in warnings:
        print(f"WARNING:{warning}", file=sys.stderr)

    for error in errors:
        print(f"ERROR:{error}", file=sys.stderr)

    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
