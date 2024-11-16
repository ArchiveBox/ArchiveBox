__package__ = 'abx_plugin_playwright'

from typing import List

from pydantic import InstanceOf
from abx_pkg import BinName, BinProvider, Binary


from abx_plugin_pip.binproviders import LIB_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER
from abx_plugin_default_binproviders import env

from .config import PLAYWRIGHT_CONFIG


class PlaywrightBinary(Binary):
    name: BinName = PLAYWRIGHT_CONFIG.PLAYWRIGHT_BINARY

    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER, env]
    

PLAYWRIGHT_BINARY = PlaywrightBinary()
