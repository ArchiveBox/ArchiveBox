__package__ = 'plugins_extractor.readability'
__label__ = 'readability'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/ArchiveBox/readability-extractor'
__dependencies__ = ['npm']

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'readability': {
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
    from .config import READABILITY_CONFIG
    
    return {
        'readability': READABILITY_CONFIG
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
