__package__ = 'plugins_extractor.readwise'
__id__ = 'readwise'
__label__ = 'readwise'
__version__ = '2024.10.21'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/ArchiveBox/ArchiveBox/tree/dev/archivebox/plugins_extractor/readwise'
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
    from .config import READWISE_CONFIG
    
    return {
        __id__: READWISE_CONFIG
    }

@abx.hookimpl
def ready():
    from .config import READWISE_CONFIG
    READWISE_CONFIG.validate()
