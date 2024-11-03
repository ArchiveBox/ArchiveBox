__package__ = 'abx_plugin_sonic_search'

import sys

from pydantic import Field

from abx_spec_config.base_configset import BaseConfigSet

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
    
    def validate(self):
        if SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_ENGINE == 'sonic' and SONIC_LIB is None:
            sys.stderr.write('[X] Error: Sonic search backend is enabled but sonic-client lib is not installed. You may need to run: pip install archivebox[sonic]\n')
            # dont hard exit here. in case the user is just running "archivebox version" or "archivebox help", we still want those to work despite broken ldap
            SEARCH_BACKEND_CONFIG.update_in_place(SEARCH_BACKEND_ENGINE='ripgrep')

SONIC_CONFIG = SonicConfig()
