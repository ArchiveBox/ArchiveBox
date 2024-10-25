__package__ = 'plugins_extractor.readability'

from typing import List

from pydantic import InstanceOf
from pydantic_pkgr import BinProvider, BinaryOverrides, BinName

from abx.archivebox.base_binary import BaseBinary, env

from plugins_pkg.npm.binproviders import SYS_NPM_BINPROVIDER, LIB_NPM_BINPROVIDER

from .config import READABILITY_CONFIG


READABILITY_PACKAGE_NAME = 'github:ArchiveBox/readability-extractor'

class ReadabilityBinary(BaseBinary):
    name: BinName = READABILITY_CONFIG.READABILITY_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER, env]

    overrides: BinaryOverrides = {
        LIB_NPM_BINPROVIDER.name: {"packages": [READABILITY_PACKAGE_NAME]},
        SYS_NPM_BINPROVIDER.name: {"packages": [READABILITY_PACKAGE_NAME], "install": lambda: None},    # prevent modifying system global npm packages
    }


READABILITY_BINARY = ReadabilityBinary()
