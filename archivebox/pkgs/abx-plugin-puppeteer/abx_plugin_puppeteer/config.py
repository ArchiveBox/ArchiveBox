__package__ = 'abx_plugin_puppeteer'


from abx_spec_config.base_configset import BaseConfigSet


###################### Config ##########################


class PuppeteerConfig(BaseConfigSet):
    PUPPETEER_BINARY: str = 'puppeteer'
    # PUPPETEER_ARGS: Optional[List[str]] = Field(default=None)
    # PUPPETEER_EXTRA_ARGS: List[str] = []
    # PUPPETEER_DEFAULT_ARGS: List[str] = ['--timeout={TIMEOUT-10}']
    pass


PUPPETEER_CONFIG = PuppeteerConfig()
