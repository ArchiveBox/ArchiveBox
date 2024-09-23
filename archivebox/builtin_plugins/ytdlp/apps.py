from typing import List, Dict, ClassVar
from subprocess import run, PIPE
from pydantic import InstanceOf, Field

from django.conf import settings

from pydantic_pkgr import BinProvider, BinName, BinProviderName, ProviderLookupDict
from plugantic.base_plugin import BasePlugin
from plugantic.base_configset import BaseConfigSet, ConfigSectionName
from plugantic.base_binary import BaseBinary, env, apt, brew
from plugantic.base_hook import BaseHook

from builtin_plugins.pip.apps import pip

###################### Config ##########################


class YtdlpDependencyConfigs(BaseConfigSet):
    section: ClassVar[ConfigSectionName] = "DEPENDENCY_CONFIG"

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
    app_label: str = 'ytdlp'
    verbose_name: str = 'YTDLP'

    hooks: List[InstanceOf[BaseHook]] = [
        YTDLP_CONFIG,
        YTDLP_BINARY,
        FFMPEG_BINARY,
    ]


PLUGIN = YtdlpPlugin()
PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
