__package__ = 'plugins_extractor.chrome'
__id__ = 'chrome'
__label__ = 'Chrome'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/ArchiveBox/ArchiveBox/tree/main/archivebox/plugins_extractor/chrome'
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
    from .config import CHROME_CONFIG
    
    return {
        __id__: CHROME_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import CHROME_BINARY
    
    return {
        'chrome': CHROME_BINARY,
    }

@abx.hookimpl
def ready():
    from .config import CHROME_CONFIG
    CHROME_CONFIG.validate()


# @abx.hookimpl
# def get_EXTRACTORS():
#     return {
#         'pdf': PDF_EXTRACTOR,
#         'screenshot': SCREENSHOT_EXTRACTOR,
#         'dom': DOM_EXTRACTOR,
#     }
