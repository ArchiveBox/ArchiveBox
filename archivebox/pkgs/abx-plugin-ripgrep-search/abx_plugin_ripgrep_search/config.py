__package__ = 'abx_plugin_ripgrep_search'

from pathlib import Path
from typing import List

from pydantic import Field

from abx_spec_config.base_configset import BaseConfigSet

from archivebox.config import CONSTANTS
from archivebox.config.common import SEARCH_BACKEND_CONFIG


class RipgrepConfig(BaseConfigSet):
    RIPGREP_BINARY: str = Field(default='rg')
    
    RIPGREP_IGNORE_EXTENSIONS: str = Field(default='css,js,orig,svg')
    RIPGREP_ARGS_DEFAULT: List[str] = Field(default=lambda c: [
        # https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md
        f'--type-add=ignore:*.{{{c.RIPGREP_IGNORE_EXTENSIONS}}}',
        '--type-not=ignore',
        '--ignore-case',
        '--files-with-matches',
        '--regexp',
    ])
    RIPGREP_SEARCH_DIR: Path = CONSTANTS.ARCHIVE_DIR
    RIPGREP_TIMEOUT: int = Field(default=lambda: SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_TIMEOUT)

RIPGREP_CONFIG = RipgrepConfig()
