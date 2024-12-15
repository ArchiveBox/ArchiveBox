import os
from pathlib import Path
from typing import Optional

from abx_pkg import NpmProvider, PATHStr, BinProviderName

import abx

DEFAULT_LIB_NPM_DIR = Path('/usr/local/share/abx/npm')

OLD_NODE_BIN_PATH = Path(os.getcwd()) / 'node_modules' / '.bin'
NEW_NODE_BIN_PATH = DEFAULT_LIB_NPM_DIR / 'node_modules' / '.bin'


class SystemNpmBinProvider(NpmProvider):
    name: BinProviderName = "sys_npm"
    
    npm_prefix: Optional[Path] = None


class LibNpmBinProvider(NpmProvider):
    name: BinProviderName = "lib_npm"
    PATH: PATHStr = f'{NEW_NODE_BIN_PATH}:{OLD_NODE_BIN_PATH}'
    
    npm_prefix: Optional[Path] = DEFAULT_LIB_NPM_DIR
    
    def setup(self) -> None:
        # update paths from config at runtime
        LIB_DIR = abx.pm.hook.get_LIB_DIR()
        self.npm_prefix = LIB_DIR / 'npm'
        self.PATH = f'{LIB_DIR / "npm" / "node_modules" / ".bin"}:{NEW_NODE_BIN_PATH}:{OLD_NODE_BIN_PATH}'
        super().setup()


SYS_NPM_BINPROVIDER = SystemNpmBinProvider()
LIB_NPM_BINPROVIDER = LibNpmBinProvider()
LIB_NPM_BINPROVIDER.setup()
npm = LIB_NPM_BINPROVIDER

LIB_NPM_BINPROVIDER.setup()
SYS_NPM_BINPROVIDER.setup()
