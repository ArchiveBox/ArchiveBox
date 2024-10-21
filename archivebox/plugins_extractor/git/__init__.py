__package__ = 'plugins_extractor.git'
__label__ = 'git'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/git/git'
__dependencies__ = []

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'git': {
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
    from .config import GIT_CONFIG
    
    return {
        'git': GIT_CONFIG
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
