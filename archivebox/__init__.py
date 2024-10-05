#!/usr/bin/env python3

# Welcome to the ArchiveBox source code! Thanks for checking it out!
#
# "We are swimming upstream against a great torrent of disorganization.
# In this, our main obligation is to establish arbitrary enclaves of order and system.
# It is the greatest possible victory to be, to continue to be, and to have been.
# No defeat can deprive us of the success of having existed for some moment of time
# in a universe that seems indifferent to us."
# --Norber Weiner

__package__ = 'archivebox'

import os
import sys
import tempfile
from pathlib import Path

ASCII_LOGO = """
 █████╗ ██████╗  ██████╗██╗  ██╗██╗██╗   ██╗███████╗ ██████╗  ██████╗ ██╗  ██╗
██╔══██╗██╔══██╗██╔════╝██║  ██║██║██║   ██║██╔════╝ ██╔══██╗██╔═══██╗╚██╗██╔╝
███████║██████╔╝██║     ███████║██║██║   ██║█████╗   ██████╔╝██║   ██║ ╚███╔╝ 
██╔══██║██╔══██╗██║     ██╔══██║██║╚██╗ ██╔╝██╔══╝   ██╔══██╗██║   ██║ ██╔██╗ 
██║  ██║██║  ██║╚██████╗██║  ██║██║ ╚████╔╝ ███████╗ ██████╔╝╚██████╔╝██╔╝ ██╗
╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═══╝  ╚══════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝
"""

SYSTEM_TMP_DIR = Path(tempfile.gettempdir()) / 'archivebox'
SYSTEM_TMP_DIR.mkdir(parents=True, exist_ok=True)
os.environ['SYSTEM_TMP_DIR'] = str(SYSTEM_TMP_DIR)
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'

# if we are outside a data dir, cd into an ephemeral tmp dir so that
# we can run version/help without polluting cwd with an index.sqlite3
if len(sys.argv) > 1 and sys.argv[1] in ('version', 'help'):
    current_dir = Path(os.getcwd()).resolve()
    if not (current_dir / 'index.sqlite3').exists():
        os.chdir(SYSTEM_TMP_DIR)

# make sure PACKAGE_DIR is in sys.path so we can import all subfolders
# without necessarily waiting for django to load them thorugh INSTALLED_APPS
PACKAGE_DIR = Path(__file__).resolve().parent
if str(PACKAGE_DIR) not in sys.path:
    sys.path.append(str(PACKAGE_DIR))


# print('INSTALLING MONKEY PATCHES')
from .monkey_patches import *                    # noqa
# print('DONE INSTALLING MONKEY PATCHES')


# print('LOADING VENDORED LIBRARIES')
from .vendor import load_vendored_libs           # noqa
load_vendored_libs()
# print('DONE LOADING VENDORED LIBRARIES')


from .config.constants import CONSTANTS, DATA_DIR, PACKAGE_DIR, ARCHIVE_DIR, VERSION  # noqa

__version__ = VERSION
__author__ = 'Nick Sweeting'
__license__ = 'MIT'

ASCII_ICON = """
██████████████████████████████████████████████████████████████████████████████████████████████████ 
██████████████████████████████████████████████████████████████████████████████████████████████████ 
██████████████████████████████████████████████████████████████████████████████████████████████████ 
██████████████████████████████████████████████████████████████████████████████████████████████████ 
██████████████████████████████████████████████████████████████████████████████████████████████████ 
██████████████████████████████████████████████████████████████████████████████████████████████████ 
██████████████████████████████████████████████████████████████████████████████████████████████████ 
         ██                                                                            ██          
         ██                                                                            ██        
         ██                                                                            ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                    ████████████████████████████████████                    ██          
         ██                    ██       █████████████████████████ █                    ██          
         ██                    ██       █████████████████████████ █                    ██          
         ██                    ██       █████████████████████████ █                    ██          
         ██                    ██       █████████████████████████ █                    ██          
         ██                    ██       █████████████████████████ █                    ██          
         ██                    ██       █████████████████████████ █                    ██          
         ██                    ██       █████████████████████████ █                    ██          
         ██                    ██       █████████████████████████ █                    ██          
         ██                    ██       █████████████████████████ █                    ██          
         ██                    ████████████████████████████████████                    ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                 ██████████████████████████████████████████                 ██          
         ██                 ██████████████████████████████████████████                 ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                                                                            ██          
         ██                                                                            ██        
         ████████████████████████████████████████████████████████████████████████████████          
"""
