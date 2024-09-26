__package__ = 'archivebox.plugins_extractor.archivedotorg'

from typing import List

from plugantic.base_plugin import BasePlugin
from plugantic.base_configset import BaseConfigSet
from plugantic.base_hook import BaseHook

###################### Config ##########################


class ArchivedotorgConfig(BaseConfigSet):
    SAVE_ARCHIVE_DOT_ORG: bool = True


ARCHIVEDOTORG_CONFIG = ArchivedotorgConfig()


class ArchivedotorgPlugin(BasePlugin):
    app_label: str = 'archivedotorg'
    verbose_name: str = 'Archive.org'
    
    hooks: List[BaseHook] = [
        ARCHIVEDOTORG_CONFIG
    ]

PLUGIN = ArchivedotorgPlugin()
DJANGO_APP = PLUGIN.AppConfig
