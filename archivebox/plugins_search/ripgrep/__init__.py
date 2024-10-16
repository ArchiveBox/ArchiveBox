__package__ = 'plugins_search.ripgrep'
__label__ = 'ripgrep'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/BurntSushi/ripgrep'
__dependencies__ = []

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'ripgrep': {
            'PACKAGE': __package__,
            'LABEL': __label__,
            'VERSION': __version__,
            'AUTHOR': __author__,
            'HOMEPAGE': __homepage__,
            'DEPENDENCIES': __dependencies__,
        }
    }

@abx.hookimpl
def get_CONFIG():
    from .config import RIPGREP_CONFIG
    
    return {
        'ripgrep': RIPGREP_CONFIG
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
