#!/usr/bin/env python3
"""
Emit forum-dl Binary dependency for the crawl.
"""

import json
import os
import sys


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()

def get_env_bool(name: str, default: bool = False) -> bool:
    val = get_env(name, '').lower()
    if val in ('true', '1', 'yes', 'on'):
        return True
    if val in ('false', '0', 'no', 'off'):
        return False
    return default


def output_binary(name: str, binproviders: str, overrides: dict | None = None):
    """Output Binary JSONL record for a dependency."""
    machine_id = os.environ.get('MACHINE_ID', '')

    record = {
        'type': 'Binary',
        'name': name,
        'binproviders': binproviders,
        'machine_id': machine_id,
    }
    if overrides:
        record['overrides'] = overrides
    print(json.dumps(record))


def main():
    forumdl_enabled = get_env_bool('FORUMDL_ENABLED', True)

    if not forumdl_enabled:
        sys.exit(0)

    output_binary(
        name='forum-dl',
        binproviders='pip,env',
        overrides={
            'pip': {
                'packages': [
                    '--no-deps',
                    'forum-dl',
                    'pydantic',
                    'pydantic-core',
                    'typing-extensions',
                    'annotated-types',
                    'typing-inspection',
                    'beautifulsoup4',
                    'soupsieve',
                    'lxml',
                    'requests',
                    'urllib3',
                    'certifi',
                    'idna',
                    'charset-normalizer',
                    'tenacity',
                    'python-dateutil',
                    'six',
                    'html2text',
                    'warcio',
                ]
            }
        },
    )

    sys.exit(0)


if __name__ == '__main__':
    main()
