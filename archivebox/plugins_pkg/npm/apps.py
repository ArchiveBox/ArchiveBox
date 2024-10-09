__package__ = 'archivebox.plugins_pkg.npm'

from pathlib import Path
from typing import List, Optional

from pydantic import InstanceOf, model_validator

from pydantic_pkgr import BinProvider, NpmProvider, BinName, PATHStr, BinProviderName

from archivebox.config import DATA_DIR, CONSTANTS

from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_binary import BaseBinary, BaseBinProvider, env, apt, brew
from abx.archivebox.base_hook import BaseHook


###################### Config ##########################


class NpmDependencyConfigs(BaseConfigSet):
    # USE_NPM: bool = True
    # NPM_BINARY: str = Field(default='npm')
    # NPM_ARGS: Optional[List[str]] = Field(default=None)
    # NPM_EXTRA_ARGS: List[str] = []
    # NPM_DEFAULT_ARGS: List[str] = []
    pass


DEFAULT_GLOBAL_CONFIG = {
}
NPM_CONFIG = NpmDependencyConfigs(**DEFAULT_GLOBAL_CONFIG)


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

class NodeBinary(BaseBinary):
    name: BinName = 'node'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]


NODE_BINARY = NodeBinary()


class NpmBinary(BaseBinary):
    name: BinName = 'npm'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

NPM_BINARY = NpmBinary()


class NpxBinary(BaseBinary):
    name: BinName = 'npx'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

NPX_BINARY = NpxBinary()





class NpmPlugin(BasePlugin):
    app_label: str = 'npm'
    verbose_name: str = 'NPM'
    
    hooks: List[InstanceOf[BaseHook]] = [
        NPM_CONFIG,
        SYS_NPM_BINPROVIDER,
        LIB_NPM_BINPROVIDER,
        NODE_BINARY,
        NPM_BINARY,
        NPX_BINARY,
    ]


PLUGIN = NpmPlugin()
# PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
