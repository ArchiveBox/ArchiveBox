__package__ = 'plugins_extractor.git'

from typing import List

from pydantic import InstanceOf
from pydantic_pkgr import BinProvider, BinName

from abx.archivebox.base_binary import BaseBinary, env, apt, brew

from .config import GIT_CONFIG



class GitBinary(BaseBinary):
    name: BinName = GIT_CONFIG.GIT_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

GIT_BINARY = GitBinary()
