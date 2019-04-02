#!/usr/bin/env python3

"""
Main ArchiveBox command line application entrypoint.
"""

__package__ = 'archivebox'

import os
import sys

PYTHON_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(PYTHON_DIR)

from .env import *
from .legacy.archive import main


if __name__ == '__main__':
    main(sys.argv)

