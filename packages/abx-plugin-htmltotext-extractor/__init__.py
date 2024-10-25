__package__ = 'plugins_extractor.htmltotext'
__id__ = 'htmltotext'
__label__ = 'HTML-to-Text'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/ArchiveBox/archivebox'
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
    from .config import HTMLTOTEXT_CONFIG
    
    return {
        __id__: HTMLTOTEXT_CONFIG
    }


# @abx.hookimpl
# def get_EXTRACTORS():
#     from .extractors import FAVICON_EXTRACTOR
    
#     return {
#         'htmltotext': FAVICON_EXTRACTOR,
#     }
