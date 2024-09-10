__package__ = 'archivebox.builtin_plugins.npm'

from typing import List, Optional
from pydantic import InstanceOf, Field

from django.conf import settings

from pydantic_pkgr import BinProvider, NpmProvider, BinName, PATHStr
from plugantic.base_plugin import BasePlugin
from plugantic.base_configset import BaseConfigSet, ConfigSectionName
from plugantic.base_binary import BaseBinary, BaseBinProvider, env, apt, brew
from plugantic.base_hook import BaseHook

from ...config import CONFIG

###################### Config ##########################


class NpmDependencyConfigs(BaseConfigSet):
    section: ConfigSectionName = 'DEPENDENCY_CONFIG'

    USE_NPM: bool = True
    NPM_BINARY: str = Field(default='npm')
    NPM_ARGS: Optional[List[str]] = Field(default=None)
    NPM_EXTRA_ARGS: List[str] = []
    NPM_DEFAULT_ARGS: List[str] = []


DEFAULT_GLOBAL_CONFIG = {
}
NPM_CONFIG = NpmDependencyConfigs(**DEFAULT_GLOBAL_CONFIG)


class CustomNpmProvider(NpmProvider, BaseBinProvider):
    PATH: PATHStr = str(CONFIG.NODE_BIN_PATH)

NPM_BINPROVIDER = CustomNpmProvider(PATH=str(CONFIG.NODE_BIN_PATH))
npm = NPM_BINPROVIDER

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
        NPM_BINPROVIDER,
        NODE_BINARY,
        NPM_BINARY,
    ]


PLUGIN = NpmPlugin()
PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
