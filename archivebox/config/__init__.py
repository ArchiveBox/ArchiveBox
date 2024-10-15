__package__ = 'archivebox.config'

from .paths import (
    PACKAGE_DIR,                                    # noqa
    DATA_DIR,                                       # noqa
    ARCHIVE_DIR,                                    # noqa
)
from .constants import CONSTANTS, CONSTANTS_CONFIG, PACKAGE_DIR, DATA_DIR, ARCHIVE_DIR      # noqa
from .version import VERSION                        # noqa


import abx


# @abx.hookimpl
# def get_INSTALLED_APPS():
#     return ['config']


@abx.hookimpl
def get_CONFIG():
    from .common import (
        SHELL_CONFIG,
        STORAGE_CONFIG,
        GENERAL_CONFIG,
        SERVER_CONFIG,
        ARCHIVING_CONFIG,
        SEARCH_BACKEND_CONFIG,
    )
    return {
        'SHELL_CONFIG': SHELL_CONFIG,
        'STORAGE_CONFIG': STORAGE_CONFIG,
        'GENERAL_CONFIG': GENERAL_CONFIG,
        'SERVER_CONFIG': SERVER_CONFIG,
        'ARCHIVING_CONFIG': ARCHIVING_CONFIG,
        'SEARCHBACKEND_CONFIG': SEARCH_BACKEND_CONFIG,
    }

