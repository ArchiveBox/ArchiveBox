__package__ = 'plugins_pkg.npm'

from pathlib import Path
from typing import Optional

from pydantic import model_validator

from pydantic_pkgr import NpmProvider, PATHStr, BinProviderName

from archivebox.config import DATA_DIR, CONSTANTS

from abx.archivebox.base_binary import BaseBinProvider



OLD_NODE_BIN_PATH = DATA_DIR / 'node_modules' / '.bin'
NEW_NODE_BIN_PATH = CONSTANTS.LIB_NPM_DIR / 'node_modules' / '.bin'


class SystemNpmBinProvider(NpmProvider, BaseBinProvider):
    name: BinProviderName = "sys_npm"
    
    npm_prefix: Optional[Path] = None


class LibNpmBinProvider(NpmProvider, BaseBinProvider):
    name: BinProviderName = "lib_npm"
    PATH: PATHStr = f'{NEW_NODE_BIN_PATH}:{OLD_NODE_BIN_PATH}'
    
    npm_prefix: Optional[Path] = CONSTANTS.LIB_NPM_DIR
    
    @model_validator(mode='after')
    def validate_path(self):
        assert self.npm_prefix == NEW_NODE_BIN_PATH.parent.parent
        return self


SYS_NPM_BINPROVIDER = SystemNpmBinProvider()
LIB_NPM_BINPROVIDER = LibNpmBinProvider()
npm = LIB_NPM_BINPROVIDER
