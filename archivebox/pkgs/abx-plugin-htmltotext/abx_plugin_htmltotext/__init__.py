__package__ = 'abx_plugin_htmltotext'
__label__ = 'HTML-to-Text'

import abx


@abx.hookimpl
def get_CONFIG():
    from .config import HTMLTOTEXT_CONFIG
    
    return {
        'HTMLTOTEXT_CONFIG': HTMLTOTEXT_CONFIG
    }


# @abx.hookimpl
# def get_EXTRACTORS():
#     from .extractors import FAVICON_EXTRACTOR
    
#     return {
#         'htmltotext': FAVICON_EXTRACTOR,
#     }
