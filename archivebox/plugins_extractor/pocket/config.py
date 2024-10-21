__package__ = 'plugins_extractor.pocket'

from typing import Dict

from pydantic import Field

from abx.archivebox.base_configset import BaseConfigSet


class PocketConfig(BaseConfigSet):
    POCKET_CONSUMER_KEY: str | None                   = Field(default=None)
    POCKET_ACCESS_TOKENS: Dict[str, str]              = Field(default=lambda: {})   # {<username>: <access_token>, ...}


POCKET_CONFIG = PocketConfig()
