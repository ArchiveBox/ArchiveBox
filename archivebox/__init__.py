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
from typing import Protocol, cast

from abx_plugins import get_plugins_dir


class _ReconfigurableStream(Protocol):
    def reconfigure(self, *, line_buffering: bool) -> object: ...

# Force unbuffered output for real-time logs
if hasattr(sys.stdout, 'reconfigure'):
    cast(_ReconfigurableStream, sys.stdout).reconfigure(line_buffering=True)
    cast(_ReconfigurableStream, sys.stderr).reconfigure(line_buffering=True)
os.environ['PYTHONUNBUFFERED'] = '1'

ASCII_LOGO = """
 █████╗ ██████╗  ██████╗██╗  ██╗██╗██╗   ██╗███████╗ ██████╗  ██████╗ ██╗  ██╗
██╔══██╗██╔══██╗██╔════╝██║  ██║██║██║   ██║██╔════╝ ██╔══██╗██╔═══██╗╚██╗██╔╝
███████║██████╔╝██║     ███████║██║██║   ██║█████╗   ██████╔╝██║   ██║ ╚███╔╝ 
██╔══██║██╔══██╗██║     ██╔══██║██║╚██╗ ██╔╝██╔══╝   ██╔══██╗██║   ██║ ██╔██╗ 
██║  ██║██║  ██║╚██████╗██║  ██║██║ ╚████╔╝ ███████╗ ██████╔╝╚██████╔╝██╔╝ ██╗
╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═══╝  ╚══════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝
"""

PACKAGE_DIR = Path(__file__).resolve().parent

# # Add PACKAGE_DIR to sys.path - required for Django migrations to import models
# # Migrations reference models like 'machine.Binary' which need to be importable
# if str(PACKAGE_DIR) not in sys.path:
#     sys.path.append(str(PACKAGE_DIR))

os.environ['DJANGO_SETTINGS_MODULE'] = 'archivebox.core.settings'
os.environ['TZ'] = 'UTC'

# detect ArchiveBox user's UID/GID based on data dir ownership
from .config.permissions import drop_privileges                 # noqa
drop_privileges()

from .misc.checks import check_not_root, check_not_inside_source_dir, check_io_encoding      # noqa
check_not_root()
check_not_inside_source_dir()
check_io_encoding()

# Install monkey patches for third-party libraries
from .misc.monkey_patches import *                    # noqa

# Plugin directories
BUILTIN_PLUGINS_DIR = Path(get_plugins_dir()).resolve()
USER_PLUGINS_DIR = Path(
    os.environ.get('ARCHIVEBOX_USER_PLUGINS_DIR')
    or os.environ.get('USER_PLUGINS_DIR')
    or os.environ.get('DATA_DIR', os.getcwd())
) / 'custom_plugins'

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
