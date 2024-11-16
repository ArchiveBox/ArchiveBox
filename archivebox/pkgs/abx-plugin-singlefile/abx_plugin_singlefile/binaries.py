from typing import List

from pydantic import InstanceOf
from abx_pkg import Binary, BinProvider, BinaryOverrides, BinName, bin_abspath

from abx_plugin_default_binproviders import env
from abx_plugin_npm.binproviders import SYS_NPM_BINPROVIDER, LIB_NPM_BINPROVIDER

from .config import SINGLEFILE_CONFIG


SINGLEFILE_MIN_VERSION = '1.1.54'
SINGLEFILE_MAX_VERSION = '1.1.60'


class SinglefileBinary(Binary):
    name: BinName = SINGLEFILE_CONFIG.SINGLEFILE_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER, env]

    overrides: BinaryOverrides = {
        LIB_NPM_BINPROVIDER.name: {
            "abspath": lambda:
                bin_abspath(SINGLEFILE_CONFIG.SINGLEFILE_BINARY, PATH=LIB_NPM_BINPROVIDER.PATH)
                or bin_abspath("single-file", PATH=LIB_NPM_BINPROVIDER.PATH)
                or bin_abspath("single-file-node.js", PATH=LIB_NPM_BINPROVIDER.PATH),
            "packages": [f"single-file-cli@>={SINGLEFILE_MIN_VERSION} <{SINGLEFILE_MAX_VERSION}"],
        },
        SYS_NPM_BINPROVIDER.name: {
            "abspath": lambda:
                bin_abspath(SINGLEFILE_CONFIG.SINGLEFILE_BINARY, PATH=SYS_NPM_BINPROVIDER.PATH)
                or bin_abspath("single-file", PATH=SYS_NPM_BINPROVIDER.PATH)
                or bin_abspath("single-file-node.js", PATH=SYS_NPM_BINPROVIDER.PATH),
            "packages": [f"single-file-cli@>={SINGLEFILE_MIN_VERSION} <{SINGLEFILE_MAX_VERSION}"],
            "install": lambda: None,
        },
        env.name: {
            'abspath': lambda:
                bin_abspath(SINGLEFILE_CONFIG.SINGLEFILE_BINARY, PATH=env.PATH)
                or bin_abspath('single-file', PATH=env.PATH)
                or bin_abspath('single-file-node.js', PATH=env.PATH),
        },
    }


SINGLEFILE_BINARY = SinglefileBinary()
