__package__ = 'abx_plugin_git'

from typing import List

from pydantic import InstanceOf
from abx_pkg import BinProvider, BinName, Binary

from abx_plugin_default_binproviders import apt, brew, env

from .config import GIT_CONFIG



class GitBinary(Binary):
    name: BinName = GIT_CONFIG.GIT_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

GIT_BINARY = GitBinary()
