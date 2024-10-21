__package__ = 'plugins_extractor.favicon'


from abx.archivebox.base_configset import BaseConfigSet


class FaviconConfig(BaseConfigSet):
    SAVE_FAVICON: bool = True
    
    FAVICON_PROVIDER: str = 'https://www.google.com/s2/favicons?domain={}'


FAVICON_CONFIG = FaviconConfig()
