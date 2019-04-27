#!/usr/bin/env python3

__package__ = 'archivebox'

import sys
from .cli import archivebox


def main():
    archivebox.main(args=sys.argv[1:], stdin=sys.stdin)


if __name__ == '__main__':
    archivebox.main(args=sys.argv[1:], stdin=sys.stdin)

