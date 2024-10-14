__package__ = 'archivebox.config'

from typing import List
from pydantic import InstanceOf

from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_hook import BaseHook


from .constants import CONSTANTS, CONSTANTS_CONFIG, PACKAGE_DIR, DATA_DIR, ARCHIVE_DIR      # noqa
from .common import (
    ShellConfig,                    # noqa: F401
    StorageConfig,                  # noqa: F401
    GeneralConfig,                  # noqa: F401
    ServerConfig,                   # noqa: F401
    ArchivingConfig,                # noqa: F401
    SearchBackendConfig,            # noqa: F401
    SHELL_CONFIG,
    STORAGE_CONFIG,
    GENERAL_CONFIG,
    SERVER_CONFIG,
    ARCHIVING_CONFIG,
    SEARCH_BACKEND_CONFIG,
)

###################### Config ##########################


class ConfigPlugin(BasePlugin):
    app_label: str = 'CONFIG'
    verbose_name: str = 'Configuration'

    hooks: List[InstanceOf[BaseHook]] = [
        SHELL_CONFIG,
        GENERAL_CONFIG,
        STORAGE_CONFIG,
        SERVER_CONFIG,
        ARCHIVING_CONFIG,
        SEARCH_BACKEND_CONFIG,
    ]


PLUGIN = ConfigPlugin()
DJANGO_APP = PLUGIN.AppConfig



# # register django apps
# @abx.hookimpl
# def get_INSTALLED_APPS():
#     return [DJANGO_APP.name]

# # register configs
# @abx.hookimpl
# def register_CONFIG():
#     return PLUGIN.HOOKS_BY_TYPE['CONFIG'].values()

