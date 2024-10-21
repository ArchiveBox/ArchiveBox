__package__ = 'plugins_pkg.pip'
__label__ = 'pip'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/pypa/pip'

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'pip': {
            'PACKAGE': __package__,
            'LABEL': __label__,
            'VERSION': __version__,
            'AUTHOR': __author__,
            'HOMEPAGE': __homepage__,
        }
    }

@abx.hookimpl
def get_CONFIG():
    from .config import PIP_CONFIG
    
    return {
        'pip': PIP_CONFIG
    }

@abx.hookimpl
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
