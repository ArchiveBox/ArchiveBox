__package__ = 'plugins_pkg.playwright'

from typing import List

from pydantic import InstanceOf
from pydantic_pkgr import BinName, BinProvider

from abx.archivebox.base_binary import BaseBinary, env

from plugins_pkg.pip.binproviders import SYS_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, LIB_PIP_BINPROVIDER

from .config import PLAYWRIGHT_CONFIG




class PlaywrightBinary(BaseBinary):
    name: BinName = PLAYWRIGHT_CONFIG.PLAYWRIGHT_BINARY

    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER, env]
    

PLAYWRIGHT_BINARY = PlaywrightBinary()
