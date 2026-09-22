#!/usr/bin/env python3

# Welcome to the ArchiveBox source code! Thanks for checking it out!
#
# "We are swimming upstream against a great torrent of disorganization.
# In this, our main obligation is to establish arbitrary enclaves of order and system.
# It is the greatest possible victory to be, to continue to be, and to have been.
# No defeat can deprive us of the success of having existed for some moment of time
# in a universe that seems indifferent to us."
# --Norber Weiner

__package__ = "archivebox"

import os
import sys
from pathlib import Path
from typing import Protocol, cast


class _ReconfigurableStream(Protocol):
    def reconfigure(self, *, line_buffering: bool) -> object: ...


# Force unbuffered output for real-time logs
if hasattr(sys.stdout, "reconfigure"):
    cast(_ReconfigurableStream, sys.stdout).reconfigure(line_buffering=True)
    cast(_ReconfigurableStream, sys.stderr).reconfigure(line_buffering=True)
os.environ["PYTHONUNBUFFERED"] = "1"

ASCII_LOGO = """
 █████╗ ██████╗  ██████╗██╗  ██╗██╗██╗   ██╗███████╗ ██████╗  ██████╗ ██╗  ██╗
██╔══██╗██╔══██╗██╔════╝██║  ██║██║██║   ██║██╔════╝ ██╔══██╗██╔═══██╗╚██╗██╔╝
███████║██████╔╝██║     ███████║██║██║   ██║█████╗   ██████╔╝██║   ██║ ╚███╔╝ 
██╔══██║██╔══██╗██║     ██╔══██║██║╚██╗ ██╔╝██╔══╝   ██╔══██╗██║   ██║ ██╔██╗ 
██║  ██║██║  ██║╚██████╗██║  ██║██║ ╚████╔╝ ███████╗ ██████╔╝╚██████╔╝██╔╝ ██╗
╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═══╝  ╚══════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝
"""

PACKAGE_DIR = Path(__file__).resolve().parent

os.environ["DJANGO_SETTINGS_MODULE"] = "archivebox.core.settings"
os.environ["TZ"] = "UTC"

# detect ArchiveBox user's UID/GID based on data dir ownership
from .config.permissions import drop_privileges  # noqa

drop_privileges()

from .misc.checks import check_not_root, check_io_encoding  # noqa

check_not_root()
check_io_encoding()

from .config.version import VERSION  # noqa


__version__ = VERSION
__author__ = "ArchiveBox"
__license__ = "MIT"


def __getattr__(name: str):
    if name == "CONSTANTS":
        from .config.constants import CONSTANTS

        os.environ.setdefault("MACHINE_ID", CONSTANTS.MACHINE_ID)
        return CONSTANTS
    if name == "DATA_DIR":
        from .config.paths import DATA_DIR

        return DATA_DIR
    if name == "VERSION":
        return VERSION
    if name in ("BUILTIN_PLUGINS_DIR", "USER_PLUGINS_DIR", "ALL_PLUGINS", "LOADED_PLUGINS"):
        from abx_plugins import get_plugins_dir
        from .config.constants import CONSTANTS

        builtin_plugins_dir = Path(get_plugins_dir()).resolve()
        user_plugins_dir = CONSTANTS.USER_PLUGINS_DIR
        plugins = {
            "builtin": builtin_plugins_dir,
            "user": user_plugins_dir,
        }
        values = {
            "BUILTIN_PLUGINS_DIR": builtin_plugins_dir,
            "USER_PLUGINS_DIR": user_plugins_dir,
            "ALL_PLUGINS": plugins,
            "LOADED_PLUGINS": plugins,
        }
        return values[name]
    raise AttributeError(name)


__all__ = (
    "ASCII_LOGO",
    "ASCII_ICON",
    "PACKAGE_DIR",
    "DATA_DIR",
    "CONSTANTS",
    "VERSION",
    "BUILTIN_PLUGINS_DIR",
    "USER_PLUGINS_DIR",
    "ALL_PLUGINS",
    "LOADED_PLUGINS",
)

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
