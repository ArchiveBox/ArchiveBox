__package__ = 'plugins_extractor.favicon'
__label__ = 'favicon'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/ArchiveBox/archivebox'
__dependencies__ = []

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'favicon': {
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
    from .config import FAVICON_CONFIG
    
    return {
        'favicon': FAVICON_CONFIG
    }


# @abx.hookimpl
# def get_EXTRACTORS():
#     from .extractors import FAVICON_EXTRACTOR
    
#     return {
#         'favicon': FAVICON_EXTRACTOR,
#     }
