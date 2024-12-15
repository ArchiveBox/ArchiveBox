__package__ = 'abx_plugin_mercury'

from typing import List

from pydantic import InstanceOf
from abx_pkg import BinProvider, BinName, BinaryOverrides, bin_abspath, Binary

from abx_plugin_default_binproviders import env

from abx_plugin_npm.binproviders import SYS_NPM_BINPROVIDER, LIB_NPM_BINPROVIDER

from .config import MERCURY_CONFIG


class MercuryBinary(Binary):
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
