__package__ = 'abx_plugin_sqlitefts_search'
__label__ = 'SQLiteFTS Search'

import abx

@abx.hookimpl
def get_CONFIG():
    from .config import SQLITEFTS_CONFIG
    
    return {
        'SQLITEFTS_CONFIG': SQLITEFTS_CONFIG
    }


@abx.hookimpl
def get_SEARCHBACKENDS():
    from .searchbackend import SQLITEFTS_SEARCH_BACKEND
    
    return {
        'sqlitefts': SQLITEFTS_SEARCH_BACKEND,
    }
