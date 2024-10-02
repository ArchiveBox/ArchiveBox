#!/usr/bin/env python3

#      _             _     _           ____            
#     / \   _ __ ___| |__ (_)_   _____| __ )  _____  __
#    / _ \ | '__/ __| '_ \| \ \ / / _ \  _ \ / _ \ \/ /
#   / ___ \| | | (__| | | | |\ V /  __/ |_) | (_) >  < 
#  /_/   \_\_|  \___|_| |_|_| \_/ \___|____/ \___/_/\_\


__package__ = 'archivebox'

import archivebox      # noqa
import sys

from .cli import main


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
