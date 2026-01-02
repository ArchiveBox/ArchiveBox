#!/usr/bin/env python3
"""
Detect mercury-parser binary and emit Binary JSONL record.

Output: Binary JSONL record to stdout if mercury-parser is found
"""

import json
import os
import sys

from abx_pkg import Binary, EnvProvider


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()

def get_env_bool(name: str, default: bool = False) -> bool:
    val = get_env(name, '').lower()
    if val in ('true', '1', 'yes', 'on'):
        return True
    if val in ('false', '0', 'no', 'off'):
        return False
    return default


def output_binary_found(binary: Binary, name: str):
    """Output Binary JSONL record for an installed binary."""
    machine_id = os.environ.get('MACHINE_ID', '')

    record = {
        'type': 'Binary',
        'name': name,
        'abspath': str(binary.abspath),
        'version': str(binary.version) if binary.version else '',
        'sha256': binary.sha256 or '',
        'binprovider': 'env',  # Already installed
        'machine_id': machine_id,
    }
    print(json.dumps(record))


def output_binary_missing(name: str, binproviders: str):
    """Output Binary JSONL record for a missing binary that needs installation."""
    machine_id = os.environ.get('MACHINE_ID', '')

    record = {
        'type': 'Binary',
        'name': name,
        'binproviders': binproviders,  # Providers that can install it
        'machine_id': machine_id,
    }
    print(json.dumps(record))


def main():
    mercury_enabled = get_env_bool('MERCURY_ENABLED', True)
    mercury_binary = get_env('MERCURY_BINARY', 'mercury-parser')

    if not mercury_enabled:
        sys.exit(0)

    provider = EnvProvider()
    try:
        binary = Binary(name=mercury_binary, binproviders=[provider]).load()
        if binary.abspath:
            # Binary found
            output_binary_found(binary, name='mercury-parser')
        else:
            # Binary not found
            output_binary_missing(name='mercury-parser', binproviders='npm')
    except Exception:
        # Binary not found
        output_binary_missing(name='mercury-parser', binproviders='npm')

    sys.exit(0)


if __name__ == '__main__':
    main()
