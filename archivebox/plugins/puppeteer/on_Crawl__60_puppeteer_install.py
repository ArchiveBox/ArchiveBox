#!/usr/bin/env python3
"""
Emit Puppeteer Binary dependency for the crawl.
"""

import json
import os
import sys


def main() -> None:
    enabled = os.environ.get('PUPPETEER_ENABLED', 'true').lower() not in ('false', '0', 'no', 'off')
    if not enabled:
        sys.exit(0)

    record = {
        'type': 'Binary',
        'name': 'puppeteer',
        'binproviders': 'npm,env',
        'overrides': {
            'npm': {
                'packages': ['puppeteer'],
            }
        },
    }
    print(json.dumps(record))
    sys.exit(0)


if __name__ == '__main__':
    main()
