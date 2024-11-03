__package__ = 'abx_plugin_singlefile'
__label__ = 'Singlefile'
__homepage__ = 'https://github.com/gildas-lormeau/singlefile'

import abx


@abx.hookimpl
def get_CONFIG():
    from .config import SINGLEFILE_CONFIG
    
    return {
        'SINGLEFILE_CONFIG': SINGLEFILE_CONFIG
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

@abx.hookimpl
def get_INSTALLED_APPS():
    # needed to load ./models.py
    return [__package__]
