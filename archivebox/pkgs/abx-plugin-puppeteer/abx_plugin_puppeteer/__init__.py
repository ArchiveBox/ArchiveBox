__package__ = 'abx_plugin_puppeteer'
__label__ = 'Puppeteer'
__homepage__ = 'https://github.com/puppeteer/puppeteer'

import abx


@abx.hookimpl
def get_CONFIG():
    from .config import PUPPETEER_CONFIG
    
    return {
        'PUPPETEER_CONFIG': PUPPETEER_CONFIG
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
