__package__ = 'abx_plugin_wget'

from typing import List


from pydantic import InstanceOf
from abx_pkg import BinProvider, BinName, Binary

from abx_plugin_default_binproviders import apt, brew, env

from .config import WGET_CONFIG


class WgetBinary(Binary):
    name: BinName = WGET_CONFIG.WGET_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

WGET_BINARY = WgetBinary()
