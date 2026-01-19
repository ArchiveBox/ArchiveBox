#!/usr/bin/env python3
"""
Emit node/npm Binary dependencies for the crawl.

This hook runs early in the Crawl lifecycle so node/npm are installed
before any npm-based extractors (e.g., puppeteer) run.
"""

import json
import os
import sys


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def output_binary(name: str, binproviders: str, overrides: dict | None = None) -> None:
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


def main() -> None:
    output_binary(
        name='node',
        binproviders='apt,brew,env',
        overrides={'apt': {'packages': ['nodejs']}},
    )

    output_binary(
        name='npm',
        binproviders='apt,brew,env',
        overrides={
            'apt': {'packages': ['nodejs', 'npm']},
            'brew': {'packages': ['node']},
        },
    )

    sys.exit(0)


if __name__ == '__main__':
    main()
