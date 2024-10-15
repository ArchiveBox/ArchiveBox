__package__ = 'plugins_extractor.chrome'
__label__ = 'chrome'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/ArchiveBox/ArchiveBox/tree/main/archivebox/plugins_extractor/chrome'
__dependencies__ = []

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'chrome': {
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
    from .config import CHROME_CONFIG
    
    return {
        'chrome': CHROME_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import CHROME_BINARY
    
    return {
        'chrome': CHROME_BINARY,
    }

# @abx.hookimpl
# def get_EXTRACTORS():
#     return {
#         'pdf': PDF_EXTRACTOR,
#         'screenshot': SCREENSHOT_EXTRACTOR,
#         'dom': DOM_EXTRACTOR,
#     }
