from typing import Dict
from pydantic import Field

from abx_spec_config import BaseConfigSet


class PocketConfig(BaseConfigSet):
    POCKET_CONSUMER_KEY: str | None                   = Field(default=None)
    POCKET_ACCESS_TOKENS: Dict[str, str]              = Field(default=dict)   # {<username>: <access_token>, ...}


POCKET_CONFIG = PocketConfig()
