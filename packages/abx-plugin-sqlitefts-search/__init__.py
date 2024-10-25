__package__ = 'plugins_search.sqlitefts'
__label__ = 'sqlitefts'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/ArchiveBox/archivebox'
__dependencies__ = []

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'sqlitefts': {
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
    from .config import SQLITEFTS_CONFIG
    
    return {
        'sqlitefts': SQLITEFTS_CONFIG
    }


@abx.hookimpl
def get_SEARCHBACKENDS():
    from .searchbackend import SQLITEFTS_SEARCH_BACKEND
    
    return {
        'sqlitefts': SQLITEFTS_SEARCH_BACKEND,
    }
