__package__ = 'abx_plugin_ripgrep_search'
__label__ = 'Ripgrep Search'
__homepage__ = 'https://github.com/BurntSushi/ripgrep'

import abx

@abx.hookimpl
def get_CONFIG():
    from .config import RIPGREP_CONFIG
    
    return {
        'RIPGREP_CONFIG': RIPGREP_CONFIG
    }


@abx.hookimpl
def get_BINARIES():
    from .binaries import RIPGREP_BINARY
    
    return {
        'ripgrep': RIPGREP_BINARY
    }


@abx.hookimpl
def get_SEARCHBACKENDS():
    from .searchbackend import RIPGREP_SEARCH_BACKEND
    
    return {
        'ripgrep': RIPGREP_SEARCH_BACKEND,
    }
