__package__ = 'abx_plugin_wget'
__label__ = 'WGET'

import abx


@abx.hookimpl
def get_CONFIG():
    from .config import WGET_CONFIG
        
    return {
        'WGET_CONFIG': WGET_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import WGET_BINARY
    
    return {
        'wget': WGET_BINARY,
    }

@abx.hookimpl
def get_EXTRACTORS():
    from .extractors import WGET_EXTRACTOR, WARC_EXTRACTOR
    
    return {
        'wget': WGET_EXTRACTOR,
        'warc': WARC_EXTRACTOR,
    }

@abx.hookimpl
def ready():
    from .config import WGET_CONFIG
    WGET_CONFIG.validate()
