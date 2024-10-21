__package__ = 'plugins_search.sonic'

from typing import List

from pydantic import InstanceOf
from pydantic_pkgr import BinProvider, BinaryOverrides, BinName

from abx.archivebox.base_binary import BaseBinary, env, brew

from .config import SONIC_CONFIG


class SonicBinary(BaseBinary):
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
