from pathlib import Path
from typing import List, Optional

from pydantic import Field

from abx_spec_config.base_configset import BaseConfigSet

from archivebox.config.common import ARCHIVING_CONFIG


class SinglefileConfig(BaseConfigSet):
    SAVE_SINGLEFILE: bool = True

    SINGLEFILE_USER_AGENT: str              = Field(default=lambda: ARCHIVING_CONFIG.USER_AGENT)
    SINGLEFILE_TIMEOUT: int                 = Field(default=lambda: ARCHIVING_CONFIG.TIMEOUT)
    SINGLEFILE_CHECK_SSL_VALIDITY: bool     = Field(default=lambda: ARCHIVING_CONFIG.CHECK_SSL_VALIDITY)
    SINGLEFILE_COOKIES_FILE: Optional[Path] = Field(default=lambda: ARCHIVING_CONFIG.COOKIES_FILE)

    SINGLEFILE_BINARY: str = Field(default='single-file')
    SINGLEFILE_EXTRA_ARGS: List[str] = []


SINGLEFILE_CONFIG = SinglefileConfig()
