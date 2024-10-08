__package__ = 'plugins_extractor.curl'

from typing import List, Optional
from pathlib import Path

from pydantic import InstanceOf, Field
from pydantic_pkgr import BinProvider, BinName

from abx.archivebox.base_plugin import BasePlugin, BaseHook
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_binary import BaseBinary, env, apt, brew
# from abx.archivebox.base_extractor import BaseExtractor, ExtractorName

from archivebox.config.common import ARCHIVING_CONFIG
from archivebox.plugins_extractor.favicon.apps import FAVICON_CONFIG
from archivebox.plugins_extractor.archivedotorg.apps import ARCHIVEDOTORG_CONFIG

class CurlConfig(BaseConfigSet):
    
    SAVE_TITLE: bool = Field(default=True)
    SAVE_HEADERS: bool = Field(default=True)
    USE_CURL: bool = Field(default=lambda c: 
        ARCHIVEDOTORG_CONFIG.SAVE_ARCHIVE_DOT_ORG
        or FAVICON_CONFIG.SAVE_FAVICON
        or c.SAVE_HEADERS
        or c.SAVE_TITLE
    )
    
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


class CurlBinary(BaseBinary):
    name: BinName = CURL_CONFIG.CURL_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

CURL_BINARY = CurlBinary()


# class CurlExtractor(BaseExtractor):
#     name: ExtractorName = 'curl'
#     binary: str = CURL_BINARY.name

#     def get_output_path(self, snapshot) -> Path | None:
#         curl_index_path = curl_output_path(snapshot.as_link())
#         if curl_index_path:
#             return Path(curl_index_path)
#         return None

# CURL_EXTRACTOR = CurlExtractor()



class CurlPlugin(BasePlugin):
    app_label: str = 'curl'
    verbose_name: str = 'CURL'
    
    hooks: List[InstanceOf[BaseHook]] = [
        CURL_CONFIG,
        CURL_BINARY,
        # CURL_EXTRACTOR,
    ]


PLUGIN = CurlPlugin()
DJANGO_APP = PLUGIN.AppConfig
