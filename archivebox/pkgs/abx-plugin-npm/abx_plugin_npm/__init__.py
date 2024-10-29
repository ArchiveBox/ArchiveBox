__label__ = 'NPM'
__author__ = 'ArchiveBox'
__homepage__ = 'https://www.npmjs.com/'

import abx


@abx.hookimpl
def get_CONFIG():
    from .config import NPM_CONFIG
    return {
        'NPM_CONFIG': NPM_CONFIG,
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
