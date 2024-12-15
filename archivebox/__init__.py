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
from typing import cast

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

# print('INSTALLING MONKEY PATCHES')
from .misc.monkey_patches import *                    # noqa
# print('DONE INSTALLING MONKEY PATCHES')


# print('LOADING VENDORED LIBRARIES')
from .pkgs import load_vendored_pkgs             # noqa
load_vendored_pkgs()
# print('DONE LOADING VENDORED LIBRARIES')

# print('LOADING ABX PLUGIN SPECIFICATIONS')
# Load ABX Plugin Specifications + Default Implementations
import abx                                       # noqa
import abx_spec_archivebox                       # noqa
import abx_spec_config                           # noqa
import abx_spec_abx_pkg                          # noqa
import abx_spec_django                           # noqa
import abx_spec_searchbackend                    # noqa

abx.pm.add_hookspecs(abx_spec_config.PLUGIN_SPEC)
abx.pm.register(abx_spec_config.PLUGIN_SPEC())

abx.pm.add_hookspecs(abx_spec_abx_pkg.PLUGIN_SPEC)
abx.pm.register(abx_spec_abx_pkg.PLUGIN_SPEC())

abx.pm.add_hookspecs(abx_spec_django.PLUGIN_SPEC)
abx.pm.register(abx_spec_django.PLUGIN_SPEC())

abx.pm.add_hookspecs(abx_spec_searchbackend.PLUGIN_SPEC)
abx.pm.register(abx_spec_searchbackend.PLUGIN_SPEC())

# Cast to ArchiveBoxPluginSpec to enable static type checking of pm.hook.call() methods
abx.pm = cast(abx.ABXPluginManager[abx_spec_archivebox.ArchiveBoxPluginSpec], abx.pm)
pm = abx.pm
# print('DONE LOADING ABX PLUGIN SPECIFICATIONS')

# Load all pip-installed ABX-compatible plugins
ABX_ECOSYSTEM_PLUGINS = abx.get_pip_installed_plugins(group='abx')

# Load all built-in ArchiveBox plugins
ARCHIVEBOX_BUILTIN_PLUGINS = {
    'config': PACKAGE_DIR / 'config',
    'workers': PACKAGE_DIR / 'workers',
    'core': PACKAGE_DIR / 'core',
    'crawls': PACKAGE_DIR / 'crawls',
    # 'machine': PACKAGE_DIR / 'machine'
    # 'search': PACKAGE_DIR / 'search',
}

# Load all user-defined ArchiveBox plugins
USER_PLUGINS = abx.find_plugins_in_dir(Path(os.getcwd()) / 'user_plugins')

# Import all plugins and register them with ABX Plugin Manager
ALL_PLUGINS = {**ABX_ECOSYSTEM_PLUGINS, **ARCHIVEBOX_BUILTIN_PLUGINS, **USER_PLUGINS}
# print('LOADING ALL PLUGINS')
LOADED_PLUGINS = abx.load_plugins(ALL_PLUGINS)
# print('DONE LOADING ALL PLUGINS')

# Setup basic config, constants, paths, and version
from .config.constants import CONSTANTS                         # noqa
from .config.paths import PACKAGE_DIR, DATA_DIR, ARCHIVE_DIR    # noqa
from .config.version import VERSION                             # noqa

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
