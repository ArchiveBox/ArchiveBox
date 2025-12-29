#!/usr/bin/env python3
"""
Install and configure ripgrep binary.

This hook runs early in the Crawl lifecycle to:
1. Install ripgrep binary if needed
2. Check if ripgrep backend is enabled
3. Output Binary JSONL records when ripgrep is found

Output:
    - COMPUTED:KEY=VALUE lines that hooks.py parses and adds to env
    - Binary JSONL records to stdout when binaries are found
"""

import json
import os
import sys

from abx_pkg import Binary, EnvProvider


# Read config from environment
def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()

def get_env_bool(name: str, default: bool = False) -> bool:
    val = get_env(name, '').lower()
    if val in ('true', '1', 'yes', 'on'):
        return True
    if val in ('false', '0', 'no', 'off'):
        return False
    return default

def get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


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


def output_machine_config(key: str, value: str):
    """Output Machine config JSONL record to stdout."""
    machine_id = os.environ.get('MACHINE_ID', '')

    record = {
        'type': 'Machine',
        'id': machine_id or 'default',
        'key': key,
        'value': value,
        'machine_id': machine_id,
    }
    print(json.dumps(record))


def main():
    warnings = []
    errors = []
    computed = {}

    # Get config values
    search_backend_engine = get_env('SEARCH_BACKEND_ENGINE', 'ripgrep')
    ripgrep_binary = get_env('RIPGREP_BINARY', 'rg')
    search_backend_timeout = get_env_int('SEARCH_BACKEND_TIMEOUT', 90)

    # Only proceed if ripgrep backend is enabled
    if search_backend_engine != 'ripgrep':
        # Not using ripgrep, exit successfully without output
        sys.exit(0)

    # Check binary availability using abx-pkg (trust abx-pkg only)
    provider = EnvProvider()
    try:
        binary = Binary(name=ripgrep_binary, binproviders=[provider]).load()
        resolved_path = str(binary.abspath) if binary.abspath else ''
    except Exception:
        binary = None
        resolved_path = ''

    if not resolved_path:
        errors.append(f"RIPGREP_BINARY={ripgrep_binary} not found. Install ripgrep: apt install ripgrep")
        computed['RIPGREP_BINARY'] = ''
    else:
        computed['RIPGREP_BINARY'] = resolved_path
        ripgrep_version = str(binary.version) if binary.version else 'unknown'
        computed['RIPGREP_VERSION'] = ripgrep_version

        # Output Binary JSONL record
        output_binary(binary, name='rg')

        # Output Machine config JSONL record
        output_machine_config('config/RIPGREP_BINARY', resolved_path)

    # Validate timeout
    if search_backend_timeout < 10:
        warnings.append(
            f"SEARCH_BACKEND_TIMEOUT={search_backend_timeout} is very low. "
            "Searches may timeout. Consider setting SEARCH_BACKEND_TIMEOUT=90 or higher."
        )

    # Output results
    # Format: KEY=VALUE lines that hooks.py will parse and add to env
    for key, value in computed.items():
        print(f"COMPUTED:{key}={value}")

    for warning in warnings:
        print(f"WARNING:{warning}", file=sys.stderr)

    for error in errors:
        print(f"ERROR:{error}", file=sys.stderr)

    # Exit with error if any hard errors
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
