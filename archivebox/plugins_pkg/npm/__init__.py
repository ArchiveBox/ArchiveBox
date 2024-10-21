__package__ = 'plugins_pkg.npm'
__label__ = 'npm'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://www.npmjs.com/'

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'npm': {
            'PACKAGE': __package__,
            'LABEL': __label__,
            'VERSION': __version__,
            'AUTHOR': __author__,
            'HOMEPAGE': __homepage__,
        }
    }

@abx.hookimpl
def get_CONFIG():
    from .config import NPM_CONFIG
    
    return {
        'npm': NPM_CONFIG,
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import NODE_BINARY, NPM_BINARY, NPX_BINARY
    
    return {
        'node': NODE_BINARY,
        'npm': NPM_BINARY,
        'npx': NPX_BINARY,
    }

@abx.hookimpl
def get_BINPROVIDERS():
    from .binproviders import LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER
    
    return {
        'sys_npm': SYS_NPM_BINPROVIDER,
        'lib_npm': LIB_NPM_BINPROVIDER,
    }
