__package__ = 'plugins_pkg.npm'
__version__ = '2024.10.14'
__id__ = 'npm'
__label__ = 'npm'
__author__ = 'ArchiveBox'
__homepage__ = 'https://www.npmjs.com/'

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
        }
    }

@abx.hookimpl
def get_CONFIG():
    from .config import NPM_CONFIG
    
    return {
        __id__: NPM_CONFIG,
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
