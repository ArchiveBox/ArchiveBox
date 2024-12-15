from abx_spec_config.base_configset import BaseConfigSet


class HtmltotextConfig(BaseConfigSet):
    SAVE_HTMLTOTEXT: bool = True


HTMLTOTEXT_CONFIG = HtmltotextConfig()
