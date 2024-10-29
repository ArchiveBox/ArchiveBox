__package__ = 'abx_plugin_mercury'

from typing import List, Optional
from pathlib import Path

from pydantic import Field

from abx_spec_config.base_configset import BaseConfigSet

from archivebox.config.common import ARCHIVING_CONFIG, STORAGE_CONFIG



class MercuryConfig(BaseConfigSet):

    SAVE_MERCURY: bool = Field(default=True, alias='USE_MERCURY')
    
    MERCURY_BINARY: str = Field(default='postlight-parser')
    MERCURY_EXTRA_ARGS: List[str] = []
    
    SAVE_MERCURY_REQUISITES: bool = Field(default=True)
    MERCURY_RESTRICT_FILE_NAMES: str = Field(default=lambda: STORAGE_CONFIG.RESTRICT_FILE_NAMES)
    
    MERCURY_TIMEOUT: int =  Field(default=lambda: ARCHIVING_CONFIG.TIMEOUT)
    MERCURY_CHECK_SSL_VALIDITY: bool = Field(default=lambda: ARCHIVING_CONFIG.CHECK_SSL_VALIDITY)
    MERCURY_USER_AGENT: str = Field(default=lambda: ARCHIVING_CONFIG.USER_AGENT)
    MERCURY_COOKIES_FILE: Optional[Path] = Field(default=lambda: ARCHIVING_CONFIG.COOKIES_FILE)
    


MERCURY_CONFIG = MercuryConfig()
