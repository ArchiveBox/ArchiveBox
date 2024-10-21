__package__ = 'plugins_extractor.wget'
__label__ = 'wget'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/ArchiveBox/ArchiveBox/tree/main/archivebox/plugins_extractor/wget'
__dependencies__ = []

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'wget': {
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
    from .config import WGET_CONFIG
        
    return {
        'wget': WGET_CONFIG
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
