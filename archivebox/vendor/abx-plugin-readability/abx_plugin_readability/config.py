from pydantic import Field

from abx_spec_config.base_configset import BaseConfigSet

from archivebox.config.common import ARCHIVING_CONFIG


class ReadabilityConfig(BaseConfigSet):
    SAVE_READABILITY: bool = Field(default=True, alias='USE_READABILITY')

    READABILITY_TIMEOUT: int                 = Field(default=lambda: ARCHIVING_CONFIG.TIMEOUT)

    READABILITY_BINARY: str = Field(default='readability-extractor')
    # READABILITY_EXTRA_ARGS: List[str] = []                                # readability-extractor doesn't take any extra args


READABILITY_CONFIG = ReadabilityConfig()
