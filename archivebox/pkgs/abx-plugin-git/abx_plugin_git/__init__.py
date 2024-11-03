__package__ = 'abx_plugin_git'
__label__ = 'Git'

import abx


@abx.hookimpl
def get_CONFIG():
    from .config import GIT_CONFIG
    
    return {
        'GIT_CONFIG': GIT_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import GIT_BINARY
    
    return {
        'git': GIT_BINARY,
    }

@abx.hookimpl
def get_EXTRACTORS():
    from .extractors import GIT_EXTRACTOR
    
    return {
        'git': GIT_EXTRACTOR,
    }
