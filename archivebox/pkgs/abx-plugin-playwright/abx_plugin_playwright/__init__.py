__label__ = 'Playwright'
__homepage__ = 'https://github.com/microsoft/playwright-python'

import abx


@abx.hookimpl
def get_CONFIG():
    from .config import PLAYWRIGHT_CONFIG
    return {
        'PLAYWRIGHT_CONFIG': PLAYWRIGHT_CONFIG
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
