__package__ = 'abx_plugin_ripgrep_search'

from typing import List

from pydantic import InstanceOf
from abx_pkg import BinProvider, BinaryOverrides, BinName, Binary

from abx_plugin_default_binproviders import apt, brew, env


from .config import RIPGREP_CONFIG


class RipgrepBinary(Binary):
    name: BinName = RIPGREP_CONFIG.RIPGREP_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

    overrides: BinaryOverrides = {
        apt.name: {'packages': ['ripgrep']},
        brew.name: {'packages': ['ripgrep']},
    }

RIPGREP_BINARY = RipgrepBinary()
