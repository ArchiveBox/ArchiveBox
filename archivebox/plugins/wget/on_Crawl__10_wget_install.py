#!/usr/bin/env python3
"""
Emit wget Binary dependency for the crawl.
"""

import json
import os
import sys


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


def output_binary(name: str, binproviders: str):
    """Output Binary JSONL record for a dependency."""
    machine_id = os.environ.get('MACHINE_ID', '')

    record = {
        'type': 'Binary',
        'name': name,
        'binproviders': binproviders,
        'machine_id': machine_id,
    }
    print(json.dumps(record))


def output_machine_config(config: dict):
    """Output Machine config JSONL patch."""
    if not config:
        return
    record = {
        'type': 'Machine',
        'config': config,
    }
    print(json.dumps(record))


def main():
    warnings = []
    errors = []

    # Get config values
    wget_enabled = get_env_bool('WGET_ENABLED', True)
    wget_save_warc = get_env_bool('WGET_SAVE_WARC', True)
    wget_timeout = get_env_int('WGET_TIMEOUT') or get_env_int('TIMEOUT', 60)
    wget_binary = get_env('WGET_BINARY', 'wget')

    # Compute derived values (USE_WGET for backward compatibility)
    use_wget = wget_enabled

    # Validate timeout with warning (not error)
    if use_wget and wget_timeout < 20:
        warnings.append(
            f"WGET_TIMEOUT={wget_timeout} is very low. "
            "wget may fail to archive sites if set to less than ~20 seconds. "
            "Consider setting WGET_TIMEOUT=60 or higher."
        )

    if use_wget:
        output_binary(name='wget', binproviders='apt,brew,pip,env')

    # Output computed config patch as JSONL
    output_machine_config({
        'USE_WGET': use_wget,
        'WGET_BINARY': wget_binary,
    })

    for warning in warnings:
        print(f"WARNING:{warning}", file=sys.stderr)

    for error in errors:
        print(f"ERROR:{error}", file=sys.stderr)

    # Exit with error if any hard errors
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
