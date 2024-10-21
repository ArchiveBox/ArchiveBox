__package__ = 'plugins_pkg.playwright'
__label__ = 'playwright'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/microsoft/playwright-python'

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'playwright': {
            'PACKAGE': __package__,
            'LABEL': __label__,
            'VERSION': __version__,
            'AUTHOR': __author__,
            'HOMEPAGE': __homepage__,
        }
    }

@abx.hookimpl
def get_CONFIG():
    from .config import PLAYWRIGHT_CONFIG
    
    return {
        'playwright': PLAYWRIGHT_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import PLAYWRIGHT_BINARY
    
    return {
        'playwright': PLAYWRIGHT_BINARY,
    }

@abx.hookimpl
def get_BINPROVIDERS():
    from .binproviders import PLAYWRIGHT_BINPROVIDER
    
    return {
        'playwright': PLAYWRIGHT_BINPROVIDER,
    }
