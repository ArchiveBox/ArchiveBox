__package__ = 'archivebox.plugins_search.sonic'

import sys
from typing import List, Dict, Generator, cast

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field, model_validator
from pydantic_pkgr import BinProvider, BinProviderName, ProviderLookupDict, BinName

# Depends on other Django apps:
from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_binary import BaseBinary, env, brew
from abx.archivebox.base_hook import BaseHook
from abx.archivebox.base_searchbackend import BaseSearchBackend

# Depends on Other Plugins:
from archivebox.config.common import SEARCH_BACKEND_CONFIG

SONIC_LIB = None
try:
    import sonic
    SONIC_LIB = sonic
except ImportError:
    SONIC_LIB = None

###################### Config ##########################

class SonicConfig(BaseConfigSet):
    SONIC_BINARY: str       = Field(default='sonic')
    
    SONIC_HOST: str         = Field(default='localhost', alias='SEARCH_BACKEND_HOST_NAME')
    SONIC_PORT: int         = Field(default=1491, alias='SEARCH_BACKEND_PORT')
    SONIC_PASSWORD: str     = Field(default='SecretPassword', alias='SEARCH_BACKEND_PASSWORD')
    SONIC_COLLECTION: str   = Field(default='archivebox')
    SONIC_BUCKET: str       = Field(default='archivebox')
    
    SONIC_MAX_CHUNK_LENGTH: int     = Field(default=2000)
    SONIC_MAX_TEXT_LENGTH: int      = Field(default=100000000)
    SONIC_MAX_RETRIES: int          = Field(default=5)

    @model_validator(mode='after')
    def validate_sonic_port(self):
        if SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_ENGINE == 'sonic' and SONIC_LIB is None:
            sys.stderr.write('[X] Error: Sonic search backend is enabled but sonic-client lib is not installed. You may need to run: pip install archivebox[sonic]\n')
            # dont hard exit here. in case the user is just running "archivebox version" or "archivebox help", we still want those to work despite broken ldap
            # sys.exit(1)
            SEARCH_BACKEND_CONFIG.update_in_place(SEARCH_BACKEND_ENGINE='ripgrep')
        return self

SONIC_CONFIG = SonicConfig()



class SonicBinary(BaseBinary):
    name: BinName = SONIC_CONFIG.SONIC_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [brew, env]   # TODO: add cargo

    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        brew.name: {'packages': lambda: ['sonic']},
        # cargo.name: {'packages': lambda: ['sonic-server']},             # TODO: add cargo
    }
    
    # TODO: add version checking over protocol? for when sonic backend is on remote server and binary is not installed locally
    # def on_get_version(self):
    #     with sonic.IngestClient(SONIC_CONFIG.SONIC_HOST, str(SONIC_CONFIG.SONIC_PORT), SONIC_CONFIG.SONIC_PASSWORD) as ingestcl:
    #         return SemVer.parse(str(ingestcl.protocol))

SONIC_BINARY = SonicBinary()



class SonicSearchBackend(BaseSearchBackend):
    name: str = 'sonic'
    docs_url: str = 'https://github.com/valeriansaliou/sonic'
    
    @staticmethod
    def index(snapshot_id: str, texts: List[str]):
        error_count = 0
        with sonic.IngestClient(SONIC_CONFIG.SONIC_HOST, str(SONIC_CONFIG.SONIC_PORT), SONIC_CONFIG.SONIC_PASSWORD) as ingestcl:
            for text in texts:
                chunks = (
                    text[i:i+SONIC_CONFIG.SONIC_MAX_CHUNK_LENGTH]
                    for i in range(
                        0,
                        min(len(text), SONIC_CONFIG.SONIC_MAX_TEXT_LENGTH),
                        SONIC_CONFIG.SONIC_MAX_CHUNK_LENGTH,
                    )
                )
                try:
                    for chunk in chunks:
                        ingestcl.push(SONIC_CONFIG.SONIC_COLLECTION, SONIC_CONFIG.SONIC_BUCKET, snapshot_id, str(chunk))
                except Exception as err:
                    print(f'[!] Sonic search backend threw an error while indexing: {err.__class__.__name__} {err}')
                    error_count += 1
                    if error_count > SONIC_CONFIG.SONIC_MAX_RETRIES:
                        raise

    @staticmethod
    def flush(snapshot_ids: Generator[str, None, None]):
        with sonic.IngestClient(SONIC_CONFIG.SONIC_HOST, str(SONIC_CONFIG.SONIC_PORT), SONIC_CONFIG.SONIC_PASSWORD) as ingestcl:
            for id in snapshot_ids:
                ingestcl.flush_object(SONIC_CONFIG.SONIC_COLLECTION, SONIC_CONFIG.SONIC_BUCKET, str(id))
    

    @staticmethod
    def search(text: str) -> List[str]:
        with sonic.SearchClient(SONIC_CONFIG.SONIC_HOST, SONIC_CONFIG.SONIC_PORT, SONIC_CONFIG.SONIC_PASSWORD) as querycl:
            snap_ids = cast(List[str], querycl.query(SONIC_CONFIG.SONIC_COLLECTION, SONIC_CONFIG.SONIC_BUCKET, text))
        return [str(id) for id in snap_ids]
    
    
SONIC_SEARCH_BACKEND = SonicSearchBackend()




class SonicSearchPlugin(BasePlugin):
    app_label: str ='sonic'
    verbose_name: str = 'Sonic'

    hooks: List[InstanceOf[BaseHook]] = [
        SONIC_CONFIG,
        SONIC_BINARY,
        SONIC_SEARCH_BACKEND,
    ]



PLUGIN = SonicSearchPlugin()
# PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
