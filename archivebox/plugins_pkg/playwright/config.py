__package__ = 'playwright'

from abx.archivebox.base_configset import BaseConfigSet


class PlaywrightConfigs(BaseConfigSet):
    PLAYWRIGHT_BINARY: str = 'playwright'


PLAYWRIGHT_CONFIG = PlaywrightConfigs()
