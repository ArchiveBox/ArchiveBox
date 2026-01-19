#!/usr/bin/env python3
"""
Emit ripgrep Binary dependency for the crawl.
"""

import os
import sys
import json


def main():
    # Only proceed if ripgrep backend is enabled
    search_backend_engine = os.environ.get('SEARCH_BACKEND_ENGINE', 'ripgrep').strip()
    if search_backend_engine != 'ripgrep':
        # Not using ripgrep, exit successfully without output
        sys.exit(0)

    machine_id = os.environ.get('MACHINE_ID', '')
    print(json.dumps({
        'type': 'Binary',
        'name': 'rg',
        'binproviders': 'apt,brew,env',
        'overrides': {
            'apt': {'packages': ['ripgrep']},
        },
        'machine_id': machine_id,
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
