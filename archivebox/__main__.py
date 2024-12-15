#!/usr/bin/env python3
"""This is the entrypoint for python -m archivebox ..."""
__package__ = 'archivebox'

import archivebox      # noqa # make sure monkey patches are applied before anything else
import sys

from .cli import main

ASCII_LOGO_MINI = r"""
     _             _     _           ____            
    / \   _ __ ___| |__ (_)_   _____| __ )  _____  __
   / _ \ | '__/ __| '_ \| \ \ / / _ \  _ \ / _ \ \/ /
  / ___ \| | | (__| | | | |\ V /  __/ |_) | (_) >  < 
 /_/   \_\_|  \___|_| |_|_| \_/ \___|____/ \___/_/\_\
"""

main(args=sys.argv[1:], stdin=sys.stdin)
