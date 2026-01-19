#!/usr/bin/env python3
"""
Emit Chromium Binary dependency for the crawl.

NOTE: We use Chromium instead of Chrome because Chrome 137+ removed support for
--load-extension and --disable-extensions-except flags, which are needed for
loading unpacked extensions in headless mode.
"""

import json
import os
import sys


def main():
    # Check if Chrome is enabled
    chrome_enabled = os.environ.get('CHROME_ENABLED', 'true').lower() not in ('false', '0', 'no', 'off')
    if not chrome_enabled:
        sys.exit(0)

    record = {
        'type': 'Binary',
        'name': 'chromium',
        'binproviders': 'puppeteer,env',
        'overrides': {
            'puppeteer': ['chromium@latest', '--install-deps'],
        },
    }
    print(json.dumps(record))
    sys.exit(0)


if __name__ == '__main__':
    main()
