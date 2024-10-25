__package__ = 'plugins_extractor.mercury'

from typing import List

from pydantic import InstanceOf
from pydantic_pkgr import BinProvider, BinName, BinaryOverrides, bin_abspath

from abx.archivebox.base_binary import BaseBinary, env

from archivebox.plugins_pkg.npm.binproviders import SYS_NPM_BINPROVIDER, LIB_NPM_BINPROVIDER

from .config import MERCURY_CONFIG


class MercuryBinary(BaseBinary):
    name: BinName = MERCURY_CONFIG.MERCURY_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER, env]

    overrides: BinaryOverrides = {
        LIB_NPM_BINPROVIDER.name: {
            'packages': ['@postlight/parser@^2.2.3'],
        },
        SYS_NPM_BINPROVIDER.name: {
            'packages': ['@postlight/parser@^2.2.3'],
            'install': lambda: None,                          # never try to install things into global prefix
        },
        env.name: {
            'version': lambda: '999.999.999' if bin_abspath('postlight-parser', PATH=env.PATH) else None,
        },
    }

MERCURY_BINARY = MercuryBinary()
