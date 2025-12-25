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
from pathlib import Path

ASCII_LOGO = """
 █████╗ ██████╗  ██████╗██╗  ██╗██╗██╗   ██╗███████╗ ██████╗  ██████╗ ██╗  ██╗
██╔══██╗██╔══██╗██╔════╝██║  ██║██║██║   ██║██╔════╝ ██╔══██╗██╔═══██╗╚██╗██╔╝
███████║██████╔╝██║     ███████║██║██║   ██║█████╗   ██████╔╝██║   ██║ ╚███╔╝ 
██╔══██║██╔══██╗██║     ██╔══██║██║╚██╗ ██╔╝██╔══╝   ██╔══██╗██║   ██║ ██╔██╗ 
██║  ██║██║  ██║╚██████╗██║  ██║██║ ╚████╔╝ ███████╗ ██████╔╝╚██████╔╝██╔╝ ██╗
╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═══╝  ╚══════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝
"""

# make sure PACKAGE_DIR is in sys.path so we can import all subfolders
# without necessarily waiting for django to load them thorugh INSTALLED_APPS
PACKAGE_DIR = Path(__file__).resolve().parent
if str(PACKAGE_DIR) not in sys.path:
    sys.path.append(str(PACKAGE_DIR))
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
os.environ['TZ'] = 'UTC'

# detect ArchiveBox user's UID/GID based on data dir ownership
from .config.permissions import drop_privileges                 # noqa
drop_privileges()

from .misc.checks import check_not_root, check_io_encoding      # noqa
check_not_root()
check_io_encoding()

# Install monkey patches for third-party libraries
from .misc.monkey_patches import *                    # noqa

# Built-in plugin directories
BUILTIN_PLUGINS_DIR = PACKAGE_DIR / 'plugins'
USER_PLUGINS_DIR = Path(os.getcwd()) / 'plugins'

# These are kept for backwards compatibility with existing code
# that checks for plugins. The new hook system uses discover_hooks()
ALL_PLUGINS = {
    'builtin': BUILTIN_PLUGINS_DIR,
    'user': USER_PLUGINS_DIR,
}
LOADED_PLUGINS = ALL_PLUGINS

# Setup basic config, constants, paths, and version
from .config.constants import CONSTANTS                         # noqa
from .config.paths import PACKAGE_DIR, DATA_DIR, ARCHIVE_DIR    # noqa
from .config.version import VERSION                             # noqa

# Set MACHINE_ID env var so hook scripts can use it
os.environ.setdefault('MACHINE_ID', CONSTANTS.MACHINE_ID)

__version__ = VERSION
__author__ = 'ArchiveBox'
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
