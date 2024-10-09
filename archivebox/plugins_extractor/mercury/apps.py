__package__ = 'plugins_extractor.mercury'

from typing import List, Optional, Dict
from pathlib import Path

from pydantic import InstanceOf, Field
from pydantic_pkgr import BinProvider, BinName, BinProviderName, ProviderLookupDict, bin_abspath

from abx.archivebox.base_plugin import BasePlugin, BaseHook
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_binary import BaseBinary, env
from abx.archivebox.base_extractor import BaseExtractor, ExtractorName

from archivebox.config.common import ARCHIVING_CONFIG, STORAGE_CONFIG
from archivebox.plugins_pkg.npm.apps import SYS_NPM_BINPROVIDER, LIB_NPM_BINPROVIDER

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


class MercuryBinary(BaseBinary):
    name: BinName = MERCURY_CONFIG.MERCURY_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER, env]

    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        LIB_NPM_BINPROVIDER.name: {
            'packages': lambda: ['@postlight/parser@^2.2.3'],
        },
        SYS_NPM_BINPROVIDER.name: {
            'packages': lambda: ['@postlight/parser@^2.2.3'],
            'install': lambda: False,                          # never try to install things into global prefix
        },
        env.name: {
            'version': lambda: '999.999.999' if bin_abspath('postlight-parser', PATH=env.PATH) else None,
        },
    }

MERCURY_BINARY = MercuryBinary()


class MercuryExtractor(BaseExtractor):
    name: ExtractorName = 'mercury'
    binary: str = MERCURY_BINARY.name

    def get_output_path(self, snapshot) -> Path | None:
        return snapshot.link_dir / 'mercury' / 'content.html'

MERCURY_EXTRACTOR = MercuryExtractor()



class MercuryPlugin(BasePlugin):
    app_label: str = 'mercury'
    verbose_name: str = 'MERCURY'
    
    hooks: List[InstanceOf[BaseHook]] = [
        MERCURY_CONFIG,
        MERCURY_BINARY,
        MERCURY_EXTRACTOR,
    ]


PLUGIN = MercuryPlugin()
DJANGO_APP = PLUGIN.AppConfig
