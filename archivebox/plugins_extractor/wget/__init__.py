__package__ = 'plugins_extractor.wget'
__id__ = 'wget'
__label__ = 'WGET'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/ArchiveBox/ArchiveBox/tree/dev/archivebox/plugins_extractor/wget'
__dependencies__ = []

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        __id__: {
            'id': __id__,
            'package': __package__,
            'label': __label__,
            'version': __version__,
            'author': __author__,
            'homepage': __homepage__,
            'dependencies': __dependencies__,
        }
    }

@abx.hookimpl
def get_CONFIG():
    from .config import WGET_CONFIG
        
    return {
        __id__: WGET_CONFIG
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
