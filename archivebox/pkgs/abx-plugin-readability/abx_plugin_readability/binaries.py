__package__ = 'abx_plugin_readability'

from typing import List

from pydantic import InstanceOf
from abx_pkg import Binary, BinProvider, BinaryOverrides, BinName

from abx_plugin_default_binproviders import env
from abx_plugin_npm.binproviders import SYS_NPM_BINPROVIDER, LIB_NPM_BINPROVIDER

from .config import READABILITY_CONFIG


READABILITY_PACKAGE_NAME = 'github:ArchiveBox/readability-extractor'

class ReadabilityBinary(Binary):
    name: BinName = READABILITY_CONFIG.READABILITY_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER, env]

    overrides: BinaryOverrides = {
        LIB_NPM_BINPROVIDER.name: {"packages": [READABILITY_PACKAGE_NAME]},
        SYS_NPM_BINPROVIDER.name: {"packages": [READABILITY_PACKAGE_NAME], "install": lambda: None},    # prevent modifying system global npm packages
    }


READABILITY_BINARY = ReadabilityBinary()
