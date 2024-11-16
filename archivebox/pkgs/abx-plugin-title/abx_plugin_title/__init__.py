import abx

# @abx.hookimpl
# def get_CONFIG():
#     from .config import TITLE_EXTRACTOR_CONFIG
    
#     return {
#         'title_extractor': TITLE_EXTRACTOR_CONFIG
#     }


@abx.hookimpl
def get_EXTRACTORS():
    from .extractors import TITLE_EXTRACTOR
    return {
        'title': TITLE_EXTRACTOR,
    }
