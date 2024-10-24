__package__ = 'plugins_extractor.curl'

from typing import List

from pydantic import InstanceOf
from pydantic_pkgr import BinProvider, BinName

from abx.archivebox.base_binary import BaseBinary, env, apt, brew


from .config import CURL_CONFIG


class CurlBinary(BaseBinary):
    name: BinName = CURL_CONFIG.CURL_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

CURL_BINARY = CurlBinary()
