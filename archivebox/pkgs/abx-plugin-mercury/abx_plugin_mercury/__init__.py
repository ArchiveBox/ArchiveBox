__package__ = 'abx_plugin_mercury'
__label__ = 'Postlight Parser'
__homepage__ = 'https://github.com/postlight/mercury-parser'

import abx

@abx.hookimpl
def get_CONFIG():
    from .config import MERCURY_CONFIG
    
    return {
        'MERCURY_CONFIG': MERCURY_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import MERCURY_BINARY
    
    return {
        'mercury': MERCURY_BINARY,
    }

@abx.hookimpl
def get_EXTRACTORS():
    from .extractors import MERCURY_EXTRACTOR
    
    return {
        'mercury': MERCURY_EXTRACTOR,
    }
