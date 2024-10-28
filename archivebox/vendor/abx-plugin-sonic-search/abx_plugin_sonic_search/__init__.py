__package__ = 'abx_plugin_sonic_search'
__label__ = 'Sonic Search'
__homepage__ = 'https://github.com/valeriansaliou/sonic'

import abx


@abx.hookimpl
def get_CONFIG():
    from .config import SONIC_CONFIG
    
    return {
        'SONIC_CONFIG': SONIC_CONFIG
    }


@abx.hookimpl
def get_BINARIES():
    from .binaries import SONIC_BINARY
    
    return {
        'sonic': SONIC_BINARY
    }


@abx.hookimpl
def get_SEARCHBACKENDS():
    from .searchbackend import SONIC_SEARCH_BACKEND
    
    return {
        'sonic': SONIC_SEARCH_BACKEND,
    }

@abx.hookimpl
def ready():
    from .config import SONIC_CONFIG
    SONIC_CONFIG.validate()
