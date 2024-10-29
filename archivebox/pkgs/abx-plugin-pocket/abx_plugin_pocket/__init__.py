__package__ = 'abx_plugin_pocket'
__label__ = 'Pocket'

import abx


@abx.hookimpl
def get_CONFIG():
    from .config import POCKET_CONFIG
    
    return {
        'POCKET_CONFIG': POCKET_CONFIG
    }

@abx.hookimpl
def ready():
    from .config import POCKET_CONFIG
    POCKET_CONFIG.validate()
