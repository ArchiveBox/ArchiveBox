__package__ = 'plugins_extractor.git'

from typing import List
from pathlib import Path

from pydantic import InstanceOf, Field
from pydantic_pkgr import BinProvider, BinName

from abx.archivebox.base_plugin import BasePlugin, BaseHook
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_binary import BaseBinary, env, apt, brew
from abx.archivebox.base_extractor import BaseExtractor, ExtractorName

from archivebox.config.common import ARCHIVING_CONFIG


class GitConfig(BaseConfigSet):

    SAVE_GIT: bool = True
    
    GIT_DOMAINS: str = Field(default='github.com,bitbucket.org,gitlab.com,gist.github.com,codeberg.org,gitea.com,git.sr.ht')
    
    GIT_BINARY: str = Field(default='git')
    GIT_ARGS: List[str] = [
        '--recursive',
    ]
    GIT_EXTRA_ARGS: List[str] = []
    
    GIT_TIMEOUT: int =  Field(default=lambda: ARCHIVING_CONFIG.TIMEOUT)
    GIT_CHECK_SSL_VALIDITY: bool = Field(default=lambda: ARCHIVING_CONFIG.CHECK_SSL_VALIDITY)
    

GIT_CONFIG = GitConfig()


class GitBinary(BaseBinary):
    name: BinName = GIT_CONFIG.GIT_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

GIT_BINARY = GitBinary()


class GitExtractor(BaseExtractor):
    name: ExtractorName = 'git'
    binary: str = GIT_BINARY.name

    def get_output_path(self, snapshot) -> Path | None:
        return snapshot.as_link() / 'git'

GIT_EXTRACTOR = GitExtractor()



class GitPlugin(BasePlugin):
    app_label: str = 'git'
    verbose_name: str = 'GIT'
    
    hooks: List[InstanceOf[BaseHook]] = [
        GIT_CONFIG,
        GIT_BINARY,
        GIT_EXTRACTOR,
    ]


PLUGIN = GitPlugin()
DJANGO_APP = PLUGIN.AppConfig
