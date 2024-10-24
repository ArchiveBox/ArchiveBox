__package__ = 'plugins_extractor.archivedotorg'
__label__ = 'archivedotorg'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://archive.org'
__dependencies__ = []

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'archivedotorg': {
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
    from .config import ARCHIVEDOTORG_CONFIG
    
    return {
        'archivedotorg': ARCHIVEDOTORG_CONFIG
    }


# @abx.hookimpl
# def get_EXTRACTORS():
#     from .extractors import ARCHIVEDOTORG_EXTRACTOR
#
#     return {
#         'archivedotorg': ARCHIVEDOTORG_EXTRACTOR,
#     }
