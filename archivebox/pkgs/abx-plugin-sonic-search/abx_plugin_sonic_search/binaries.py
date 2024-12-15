__package__ = 'abx_plugin_sonic_search'

from typing import List

from pydantic import InstanceOf
from abx_pkg import BinProvider, BinaryOverrides, BinName, Binary

from abx_plugin_default_binproviders import brew, env

from .config import SONIC_CONFIG


class SonicBinary(Binary):
    name: BinName = SONIC_CONFIG.SONIC_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [brew, env]   # TODO: add cargo

    overrides: BinaryOverrides = {
        brew.name: {'packages': ['sonic']},
        # cargo.name: {'packages': ['sonic-server']},                     # TODO: add cargo
    }
    
    # TODO: add version checking over protocol? for when sonic backend is on remote server and binary is not installed locally
    # def on_get_version(self):
    #     with sonic.IngestClient(SONIC_CONFIG.SONIC_HOST, str(SONIC_CONFIG.SONIC_PORT), SONIC_CONFIG.SONIC_PASSWORD) as ingestcl:
    #         return SemVer.parse(str(ingestcl.protocol))

SONIC_BINARY = SonicBinary()
