__package__ = 'plugins_extractor.curl'
__label__ = 'curl'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/curl/curl'
__dependencies__ = []

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'curl': {
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
    from .config import CURL_CONFIG
    
    return {
        'curl': CURL_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import CURL_BINARY
    
    return {
        'curl': CURL_BINARY,
    }
