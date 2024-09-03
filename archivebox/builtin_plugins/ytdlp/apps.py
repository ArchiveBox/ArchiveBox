import sys
import shutil
from pathlib import Path
from typing import List, Dict, Optional
from subprocess import run, PIPE, CompletedProcess
from pydantic import InstanceOf, Field

from django.apps import AppConfig

from pydantic_pkgr import BinProvider, BinName, PATHStr, BinProviderName, ProviderLookupDict
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
    binproviders_supported: List[InstanceOf[BinProvider]] = [pip, apt, brew, env]

class FfmpegBinary(BaseBinary):
    name: BinName = 'ffmpeg'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        'env': {
            # 'abspath': lambda: shutil.which('ffmpeg', PATH=env.PATH),
            # 'version': lambda: run(['ffmpeg', '-version'], stdout=PIPE, stderr=PIPE, text=True).stdout,
        },
        'apt': {
            # 'abspath': lambda: shutil.which('ffmpeg', PATH=apt.PATH),
            'version': lambda: run(['apt', 'show', 'ffmpeg'], stdout=PIPE, stderr=PIPE, text=True).stdout,
        },
        'brew': {
            # 'abspath': lambda: shutil.which('ffmpeg', PATH=brew.PATH),
            'version': lambda: run(['brew', 'info', 'ffmpeg', '--quiet'], stdout=PIPE, stderr=PIPE, text=True).stdout,
        },
    }

    # def get_ffmpeg_version(self) -> Optional[str]:
    #     return self.exec(cmd=['-version']).stdout


YTDLP_BINARY = YtdlpBinary()
FFMPEG_BINARY = FfmpegBinary()

# class YtdlpExtractor(BaseExtractor):
#     name: str = 'ytdlp'
#     binary: str = 'ytdlp'



class YtdlpPlugin(BasePlugin):
    name: str = 'builtin_plugins.ytdlp'
    app_label: str = 'ytdlp'
    verbose_name: str = 'YTDLP'

    configs: List[InstanceOf[BaseConfigSet]] = [YTDLP_CONFIG]
    binaries: List[InstanceOf[BaseBinary]] = [YTDLP_BINARY, FFMPEG_BINARY]


PLUGIN = YtdlpPlugin()
DJANGO_APP = PLUGIN.AppConfig
