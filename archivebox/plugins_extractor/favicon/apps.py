__package__ = 'archivebox.plugins_extractor.favicon'

from typing import List

from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_hook import BaseHook

###################### Config ##########################


class FaviconConfig(BaseConfigSet):
    SAVE_FAVICON: bool = True
    
    FAVICON_PROVIDER: str = 'https://www.google.com/s2/favicons?domain={}'


FAVICON_CONFIG = FaviconConfig()


class FaviconPlugin(BasePlugin):
    app_label: str = 'favicon'
    verbose_name: str = 'Favicon'
    
    hooks: List[BaseHook] = [
        FAVICON_CONFIG
    ]

PLUGIN = FaviconPlugin()
DJANGO_APP = PLUGIN.AppConfig
