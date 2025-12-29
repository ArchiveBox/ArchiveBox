#!/usr/bin/env python3
"""
Validate and compute derived wget config values.

This hook runs early in the Crawl lifecycle to:
1. Validate config values with warnings (not hard errors)
2. Compute derived values (USE_WGET from WGET_ENABLED)
3. Check binary availability and version

Output:
    - COMPUTED:KEY=VALUE lines that hooks.py parses and adds to env
    - Binary JSONL records to stdout when binaries are found
"""

import json
import os
import shutil
import subprocess
import sys

from abx_pkg import Binary, EnvProvider


# Read config from environment (already validated by JSONSchema)
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


def main():
    warnings = []
    errors = []
    computed = {}

    # Get config values
    wget_enabled = get_env_bool('WGET_ENABLED', True)
    wget_save_warc = get_env_bool('WGET_SAVE_WARC', True)
    wget_timeout = get_env_int('WGET_TIMEOUT') or get_env_int('TIMEOUT', 60)
    wget_binary = get_env('WGET_BINARY', 'wget')

    # Compute derived values (USE_WGET for backward compatibility)
    use_wget = wget_enabled
    computed['USE_WGET'] = str(use_wget).lower()

    # Validate timeout with warning (not error)
    if use_wget and wget_timeout < 20:
        warnings.append(
            f"WGET_TIMEOUT={wget_timeout} is very low. "
            "wget may fail to archive sites if set to less than ~20 seconds. "
            "Consider setting WGET_TIMEOUT=60 or higher."
        )

    # Check binary availability using abx-pkg
    provider = EnvProvider()
    try:
        binary = Binary(name=wget_binary, binproviders=[provider]).load()
        binary_path = str(binary.abspath) if binary.abspath else ''
    except Exception:
        binary = None
        binary_path = ''

    if not binary_path:
        if use_wget:
            errors.append(f"WGET_BINARY={wget_binary} not found. Install wget or set WGET_ENABLED=false.")
        computed['WGET_BINARY'] = ''
    else:
        computed['WGET_BINARY'] = binary_path
        wget_version = str(binary.version) if binary.version else 'unknown'
        computed['WGET_VERSION'] = wget_version

        # Output Binary JSONL record
        output_binary(binary, name='wget')

    # Check for compression support
    if computed.get('WGET_BINARY'):
        try:
            result = subprocess.run(
                [computed['WGET_BINARY'], '--compression=auto', '--help'],
                capture_output=True, timeout=5
            )
            computed['WGET_AUTO_COMPRESSION'] = 'true' if result.returncode == 0 else 'false'
        except Exception:
            computed['WGET_AUTO_COMPRESSION'] = 'false'

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
