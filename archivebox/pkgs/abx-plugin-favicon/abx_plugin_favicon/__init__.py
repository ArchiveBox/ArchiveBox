__label__ = 'Favicon'
__version__ = '2024.10.24'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/ArchiveBox/archivebox'
__dependencies__ = [
    'abx>=0.1.0',
    'abx-spec-config>=0.1.0',
    'abx-plugin-curl-extractor>=2024.10.24',
]

import abx


@abx.hookimpl
def get_CONFIG():
    from .config import FAVICON_CONFIG
    
    return {
        'FAVICON_CONFIG': FAVICON_CONFIG
    }


@abx.hookimpl
def get_EXTRACTORS():
    from .extractors import FAVICON_EXTRACTOR
    
    return {
        'favicon': FAVICON_EXTRACTOR,
    }
