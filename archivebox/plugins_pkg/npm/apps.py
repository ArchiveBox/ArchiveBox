__package__ = 'archivebox.plugins_pkg.npm'

import archivebox

from pathlib import Path
from typing import List, Optional

from django.conf import settings

from pydantic import InstanceOf, model_validator

from pydantic_pkgr import BinProvider, NpmProvider, BinName, PATHStr, BinProviderName

from plugantic.base_plugin import BasePlugin
from plugantic.base_configset import BaseConfigSet
from plugantic.base_binary import BaseBinary, BaseBinProvider, env, apt, brew
from plugantic.base_hook import BaseHook


###################### Config ##########################


class NpmDependencyConfigs(BaseConfigSet):
    # section: ConfigSectionName = 'DEPENDENCY_CONFIG'

    # USE_NPM: bool = True
    # NPM_BINARY: str = Field(default='npm')
    # NPM_ARGS: Optional[List[str]] = Field(default=None)
    # NPM_EXTRA_ARGS: List[str] = []
    # NPM_DEFAULT_ARGS: List[str] = []
    pass


DEFAULT_GLOBAL_CONFIG = {
}
NPM_CONFIG = NpmDependencyConfigs(**DEFAULT_GLOBAL_CONFIG)


OLD_NODE_BIN_PATH = archivebox.DATA_DIR / 'node_modules' / '.bin'
NEW_NODE_BIN_PATH = archivebox.CONSTANTS.LIB_NPM_DIR / 'node_modules' / '.bin'

class SystemNpmProvider(NpmProvider, BaseBinProvider):
    name: BinProviderName = "sys_npm"
    
    npm_prefix: Optional[Path] = None

class LibNpmProvider(NpmProvider, BaseBinProvider):
    name: BinProviderName = "lib_npm"
    PATH: PATHStr = str(OLD_NODE_BIN_PATH)
    
    npm_prefix: Optional[Path] = archivebox.CONSTANTS.LIB_NPM_DIR
    
    @model_validator(mode='after')
    def validate_path(self):
        assert self.npm_prefix == NEW_NODE_BIN_PATH.parent.parent
        return self


SYS_NPM_BINPROVIDER = SystemNpmProvider()
LIB_NPM_BINPROVIDER = LibNpmProvider()
npm = LIB_NPM_BINPROVIDER

class NpmBinary(BaseBinary):
    name: BinName = 'npm'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]


NPM_BINARY = NpmBinary()

class NodeBinary(BaseBinary):
    name: BinName = 'node'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]


NODE_BINARY = NodeBinary()



class NpmPlugin(BasePlugin):
    app_label: str = 'npm'
    verbose_name: str = 'NPM'
    
    hooks: List[InstanceOf[BaseHook]] = [
        NPM_CONFIG,
        SYS_NPM_BINPROVIDER,
        LIB_NPM_BINPROVIDER,
        NODE_BINARY,
        NPM_BINARY,
    ]


PLUGIN = NpmPlugin()
# PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
