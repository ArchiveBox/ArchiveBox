__package__ = 'abx_plugin_curl'

from typing import List

from pydantic import InstanceOf
from abx_pkg import BinProvider, BinName, Binary

from abx_plugin_default_binproviders import apt, brew, env


from .config import CURL_CONFIG


class CurlBinary(Binary):
    name: BinName = CURL_CONFIG.CURL_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

CURL_BINARY = CurlBinary()
