#!/usr/bin/env python3

__package__ = 'archivebox'

import sys

from .cli import main


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
