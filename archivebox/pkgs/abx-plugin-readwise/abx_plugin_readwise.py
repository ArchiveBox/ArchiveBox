__package__ = 'abx_plugin_readwise_extractor'
__id__ = 'abx_plugin_readwise_extractor'
__label__ = 'Readwise API'
__version__ = '2024.10.27'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/ArchiveBox/ArchiveBox/tree/dev/archivebox/pkgs/abx-plugin-readwise-extractor'
__dependencies__ = []

import abx

from typing import Dict
from pathlib import Path

from pydantic import Field

from abx_spec_config.base_configset import BaseConfigSet

SOURCES_DIR = abx.pm.hook.get_CONFIG().SOURCES_DIR


class ReadwiseConfig(BaseConfigSet):
    READWISE_DB_PATH: Path                  = Field(default=SOURCES_DIR / "readwise_reader_api.db")
    READWISE_READER_TOKENS: Dict[str, str]  = Field(default=lambda: {})   # {<username>: <access_token>, ...}


@abx.hookimpl
def get_CONFIG():
    return {
        __id__: ReadwiseConfig()
    }

@abx.hookimpl
def ready():
    READWISE_CONFIG = abx.pm.hook.get_CONFIG()[__id__]
    READWISE_CONFIG.validate()
