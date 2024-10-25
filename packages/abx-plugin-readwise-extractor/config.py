__package__ = 'plugins_extractor.readwise'

from typing import Dict
from pathlib import Path

from pydantic import Field

from abx.archivebox.base_configset import BaseConfigSet

from archivebox.config import CONSTANTS


class ReadwiseConfig(BaseConfigSet):
    READWISE_DB_PATH: Path                  = Field(default=CONSTANTS.SOURCES_DIR / "readwise_reader_api.db")
    READWISE_READER_TOKENS: Dict[str, str]  = Field(default=lambda: {})   # {<username>: <access_token>, ...}

READWISE_CONFIG = ReadwiseConfig()
