__package__ = 'plugins_extractor.wget'

from typing import List


from pydantic import InstanceOf
from pydantic_pkgr import BinProvider, BinName

from abx.archivebox.base_binary import BaseBinary, env, apt, brew

from .config import WGET_CONFIG


class WgetBinary(BaseBinary):
    name: BinName = WGET_CONFIG.WGET_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

WGET_BINARY = WgetBinary()
