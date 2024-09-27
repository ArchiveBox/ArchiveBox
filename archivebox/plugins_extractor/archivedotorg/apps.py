__package__ = 'archivebox.plugins_extractor.archivedotorg'

from typing import List

from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_hook import BaseHook

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
