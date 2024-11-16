__package__ = 'abx_plugin_pip'
__label__ = 'PIP'
__order__ = 200

import abx


@abx.hookimpl
def get_CONFIG():
    from .config import PIP_CONFIG
    
    return {
        'PIP_CONFIG': PIP_CONFIG
    }

@abx.hookimpl(tryfirst=True)
def get_BINARIES():
    from .binaries import ARCHIVEBOX_BINARY, PYTHON_BINARY, DJANGO_BINARY, SQLITE_BINARY, PIP_BINARY, PIPX_BINARY
    
    return {
        'archivebox': ARCHIVEBOX_BINARY,
        'python': PYTHON_BINARY,
        'django': DJANGO_BINARY,
        'sqlite': SQLITE_BINARY,
        'pip': PIP_BINARY,
        'pipx': PIPX_BINARY,
    }

@abx.hookimpl
def get_BINPROVIDERS():
    from .binproviders import SYS_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, LIB_PIP_BINPROVIDER
    
    return {
        'sys_pip': SYS_PIP_BINPROVIDER,
        'venv_pip': VENV_PIP_BINPROVIDER,
        'lib_pip': LIB_PIP_BINPROVIDER,
    }
