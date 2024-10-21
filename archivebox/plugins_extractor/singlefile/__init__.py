__package__ = 'plugins_extractor.singlefile'
__label__ = 'singlefile'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/gildas-lormeau/singlefile'
__dependencies__ = ['npm']

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'singlefile': {
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
    from .config import SINGLEFILE_CONFIG
    
    return {
        'singlefile': SINGLEFILE_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import SINGLEFILE_BINARY
    
    return {
        'singlefile': SINGLEFILE_BINARY,
    }

@abx.hookimpl
def get_EXTRACTORS():
    from .extractors import SINGLEFILE_EXTRACTOR
    
    return {
        'singlefile': SINGLEFILE_EXTRACTOR,
    }

# @abx.hookimpl
# def get_INSTALLED_APPS():
#     # needed to load ./models.py
#     return [__package__]
