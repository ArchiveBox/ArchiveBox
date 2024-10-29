__package__ = 'abx_plugin_curl'

from typing import List, Optional
from pathlib import Path

from pydantic import Field

from abx_spec_config.base_configset import BaseConfigSet

from archivebox.config.common import ARCHIVING_CONFIG


class CurlConfig(BaseConfigSet):
    
    SAVE_TITLE: bool = Field(default=True)
    SAVE_HEADERS: bool = Field(default=True)
    USE_CURL: bool = Field(default=True)
    
    CURL_BINARY: str = Field(default='curl')
    CURL_ARGS: List[str] = [
        '--silent',
        '--location',
        '--compressed',
    ]
    CURL_EXTRA_ARGS: List[str] = []
    
    CURL_TIMEOUT: int =  Field(default=lambda: ARCHIVING_CONFIG.TIMEOUT)
    CURL_CHECK_SSL_VALIDITY: bool = Field(default=lambda: ARCHIVING_CONFIG.CHECK_SSL_VALIDITY)
    CURL_USER_AGENT: str = Field(default=lambda: ARCHIVING_CONFIG.USER_AGENT)
    CURL_COOKIES_FILE: Optional[Path] = Field(default=lambda: ARCHIVING_CONFIG.COOKIES_FILE)
    

CURL_CONFIG = CurlConfig()
