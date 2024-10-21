__package__ = 'plugins_search.ripgrep'

from typing import List

from pydantic import InstanceOf
from pydantic_pkgr import BinProvider, BinaryOverrides, BinName

from abx.archivebox.base_binary import BaseBinary, env, apt, brew


from .config import RIPGREP_CONFIG


class RipgrepBinary(BaseBinary):
    name: BinName = RIPGREP_CONFIG.RIPGREP_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

    overrides: BinaryOverrides = {
        apt.name: {'packages': ['ripgrep']},
        brew.name: {'packages': ['ripgrep']},
    }

RIPGREP_BINARY = RipgrepBinary()
