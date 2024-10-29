__label__ = 'Archive.org'
__homepage__ = 'https://archive.org'

import abx

@abx.hookimpl
def get_CONFIG():
    from .config import ARCHIVEDOTORG_CONFIG
    
    return {
        'ARCHIVEDOTORG_CONFIG': ARCHIVEDOTORG_CONFIG
    }


# @abx.hookimpl
# def get_EXTRACTORS():
#     from .extractors import ARCHIVEDOTORG_EXTRACTOR
#
#     return {
#         'archivedotorg': ARCHIVEDOTORG_EXTRACTOR,
#     }
