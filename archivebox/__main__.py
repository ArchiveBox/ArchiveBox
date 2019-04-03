#!/usr/bin/env python3

__package__ = 'archivebox'


import os
import sys

PYTHON_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(PYTHON_DIR)

from .cli.archivebox import main


if __name__ == '__main__':
    main(sys.argv)

