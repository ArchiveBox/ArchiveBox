__package__ = 'archivebox.builtin_plugins.npm'

from pathlib import Path
from typing import List, Dict, Optional
from pydantic import InstanceOf, Field

from django.apps import AppConfig
from django.conf import settings

from pydantic_pkgr import BinProvider, NpmProvider, BinName, PATHStr
from plugantic.base_plugin import BasePlugin, BaseConfigSet, BaseBinary, BaseBinProvider
from plugantic.base_configset import ConfigSectionName

from pkg.settings import env, apt, brew

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


class NpmProvider(NpmProvider, BaseBinProvider):
    PATH: PATHStr = str(CONFIG.NODE_BIN_PATH)

npm = NpmProvider(PATH=str(CONFIG.NODE_BIN_PATH))

class NpmBinary(BaseBinary):
    name: BinName = 'npm'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]


NPM_BINARY = NpmBinary()

class NodeBinary(BaseBinary):
    name: BinName = 'node'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]


NODE_BINARY = NodeBinary()



class NpmPlugin(BasePlugin):
    name: str = 'builtin_plugins.npm'
    app_label: str = 'npm'
    verbose_name: str = 'NPM'

    configs: List[InstanceOf[BaseConfigSet]] = [NPM_CONFIG]
    binproviders: List[InstanceOf[BaseBinProvider]] = [npm]
    binaries: List[InstanceOf[BaseBinary]] = [NODE_BINARY, NPM_BINARY]


PLUGIN = NpmPlugin()
DJANGO_APP = PLUGIN.AppConfig
# CONFIGS = PLUGIN.configs
# BINARIES = PLUGIN.binaries
# EXTRACTORS = PLUGIN.extractors
# REPLAYERS = PLUGIN.replayers
# CHECKS = PLUGIN.checks
