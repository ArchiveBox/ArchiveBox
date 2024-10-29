__package__ = 'abx_plugin_git'

from typing import List

from pydantic import Field

from abx_spec_config.base_configset import BaseConfigSet

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
