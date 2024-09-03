import sys
from pathlib import Path
from typing import List, Dict, Optional
from pydantic import InstanceOf, Field

from django.apps import AppConfig

from pydantic_pkgr import BinProvider, PipProvider, BinName, PATHStr
from plugantic.base_plugin import BasePlugin, BaseConfigSet, BaseBinary, BaseBinProvider
from plugantic.base_configset import ConfigSectionName

from pkg.settings import env, apt, brew


###################### Config ##########################


class PipDependencyConfigs(BaseConfigSet):
    section: ConfigSectionName = 'DEPENDENCY_CONFIG'

    USE_PIP: bool = True
    PIP_BINARY: str = Field(default='pip')
    PIP_ARGS: Optional[List[str]] = Field(default=None)
    PIP_EXTRA_ARGS: List[str] = []
    PIP_DEFAULT_ARGS: List[str] = []


DEFAULT_GLOBAL_CONFIG = {
}
PIP_CONFIG = PipDependencyConfigs(**DEFAULT_GLOBAL_CONFIG)

class PipProvider(PipProvider, BaseBinProvider):
    PATH: PATHStr = str(Path(sys.executable).parent)

pip = PipProvider(PATH=str(Path(sys.executable).parent))


class PipBinary(BaseBinary):
    name: BinName = 'pip'
    binproviders_supported: List[InstanceOf[BinProvider]] = [env, pip, apt, brew]
PIP_BINARY = PipBinary()








class PipPlugin(BasePlugin):
    name: str = 'builtin_plugins.pip'
    app_label: str = 'pip'
    verbose_name: str = 'PIP'

    configs: List[InstanceOf[BaseConfigSet]] = [PIP_CONFIG]
    binproviders: List[InstanceOf[BaseBinProvider]] = [pip]
    binaries: List[InstanceOf[BaseBinary]] = [PIP_BINARY]


PLUGIN = PipPlugin()
DJANGO_APP = PLUGIN.AppConfig
# CONFIGS = PLUGIN.configs
# BINARIES = PLUGIN.binaries
# EXTRACTORS = PLUGIN.extractors
# REPLAYERS = PLUGIN.replayers
# CHECKS = PLUGIN.checks
