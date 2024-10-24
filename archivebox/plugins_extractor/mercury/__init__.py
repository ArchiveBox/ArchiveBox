__package__ = 'plugins_extractor.mercury'
__label__ = 'mercury'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/postlight/mercury-parser'
__dependencies__ = ['npm']

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'mercury': {
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
    from .config import MERCURY_CONFIG
    
    return {
        'mercury': MERCURY_CONFIG
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
