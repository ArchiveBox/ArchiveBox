__package__ = 'abx_plugin_readability'
__label__ = 'Readability'
__homepage__ = 'https://github.com/ArchiveBox/readability-extractor'

import abx


@abx.hookimpl
def get_CONFIG():
    from .config import READABILITY_CONFIG
    
    return {
        'READABILITY_CONFIG': READABILITY_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import READABILITY_BINARY
    
    return {
        'readability': READABILITY_BINARY,
    }

@abx.hookimpl
def get_EXTRACTORS():
    from .extractors import READABILITY_EXTRACTOR
    
    return {
        'readability': READABILITY_EXTRACTOR,
    }
