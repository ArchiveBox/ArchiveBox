import sys
from pathlib import Path
from typing import List, Dict, Optional
from pydantic import InstanceOf, Field

from django.apps import AppConfig

from pydantic_pkgr import BinProvider, BinName, PATHStr
from plugantic.base_plugin import BasePlugin, BaseConfigSet, BaseBinary, BaseBinProvider
from plugantic.base_configset import ConfigSectionName

from pkg.settings import env, apt, brew

from builtin_plugins.pip.apps import pip

###################### Config ##########################


class YtdlpDependencyConfigs(BaseConfigSet):
    section: ConfigSectionName = 'DEPENDENCY_CONFIG'

    USE_YTDLP: bool = True

    YTDLP_BINARY: str = Field(default='yt-dlp')

DEFAULT_GLOBAL_CONFIG = {}
YTDLP_CONFIG = YtdlpDependencyConfigs(**DEFAULT_GLOBAL_CONFIG)



class YtdlpBinary(BaseBinary):
    name: BinName = YTDLP_CONFIG.YTDLP_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [env, pip, apt, brew]

YTDLP_BINARY = YtdlpBinary()


class YtdlpPlugin(BasePlugin):
    name: str = 'builtin_plugins.ytdlp'
    app_label: str = 'ytdlp'
    verbose_name: str = 'YTDLP'

    configs: List[InstanceOf[BaseConfigSet]] = [YTDLP_CONFIG]
    binaries: List[InstanceOf[BaseBinary]] = [YTDLP_BINARY]


PLUGIN = YtdlpPlugin()
DJANGO_APP = PLUGIN.AppConfig
