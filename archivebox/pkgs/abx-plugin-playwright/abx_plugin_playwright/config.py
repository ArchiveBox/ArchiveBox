from abx_spec_config import BaseConfigSet

class PlaywrightConfigs(BaseConfigSet):
    PLAYWRIGHT_BINARY: str = 'playwright'


PLAYWRIGHT_CONFIG = PlaywrightConfigs()
