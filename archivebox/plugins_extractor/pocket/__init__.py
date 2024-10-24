__package__ = 'plugins_extractor.pocket'
__id__ = 'pocket'
__label__ = 'pocket'
__version__ = '2024.10.21'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/ArchiveBox/ArchiveBox/tree/dev/archivebox/plugins_extractor/pocket'
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
    from .config import POCKET_CONFIG
    
    return {
        __id__: POCKET_CONFIG
    }

@abx.hookimpl
def ready():
    from .config import POCKET_CONFIG
    POCKET_CONFIG.validate()
