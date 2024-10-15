__package__ = 'plugins_pkg.puppeteer'
__label__ = 'puppeteer'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/puppeteer/puppeteer'
__dependencies__ = ['npm']

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'puppeteer': {
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
    from .config import PUPPETEER_CONFIG
    
    return {
        'puppeteer': PUPPETEER_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import PUPPETEER_BINARY
    
    return {
        'puppeteer': PUPPETEER_BINARY,
    }

@abx.hookimpl
def get_BINPROVIDERS():
    from .binproviders import PUPPETEER_BINPROVIDER
    
    return {
        'puppeteer': PUPPETEER_BINPROVIDER,
    }
