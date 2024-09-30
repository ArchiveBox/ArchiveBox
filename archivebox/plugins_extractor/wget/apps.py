from typing import List
from abx.archivebox.base_plugin import BasePlugin, InstanceOf, BaseHook


# class WgetToggleConfig(ConfigSet):

#     SAVE_WGET: bool = True
#     SAVE_WARC: bool = True

# class WgetDependencyConfig(ConfigSet):

#     WGET_BINARY: str = Field(default='wget')
#     WGET_ARGS: Optional[List[str]] = Field(default=None)
#     WGET_EXTRA_ARGS: List[str] = []
#     WGET_DEFAULT_ARGS: List[str] = ['--timeout={TIMEOUT-10}']

# class WgetOptionsConfig(ConfigSet):

#     # loaded from shared config
#     WGET_AUTO_COMPRESSION: bool = Field(default=True)
#     SAVE_WGET_REQUISITES: bool = Field(default=True)
#     WGET_USER_AGENT: str = Field(default='', alias='USER_AGENT')
#     WGET_TIMEOUT: int = Field(default=60, alias='TIMEOUT')
#     WGET_CHECK_SSL_VALIDITY: bool = Field(default=True, alias='CHECK_SSL_VALIDITY')
#     WGET_RESTRICT_FILE_NAMES: str = Field(default='windows', alias='RESTRICT_FILE_NAMES')
#     WGET_COOKIES_FILE: Optional[Path] = Field(default=None, alias='COOKIES_FILE')


# CONFIG = {
#     'CHECK_SSL_VALIDITY': False,
#     'SAVE_WARC': False,
#     'TIMEOUT': 999,
# }


# WGET_CONFIG = [
#     WgetToggleConfig(**CONFIG),
#     WgetDependencyConfig(**CONFIG),
#     WgetOptionsConfig(**CONFIG),
# ]



# class WgetExtractor(Extractor):
#     name: ExtractorName = 'wget'
#     binary: Binary = WgetBinary()

#     def get_output_path(self, snapshot) -> Path:
#         return get_wget_output_path(snapshot)


# class WarcExtractor(Extractor):
#     name: ExtractorName = 'warc'
#     binary: Binary = WgetBinary()

#     def get_output_path(self, snapshot) -> Path:
#         return get_wget_output_path(snapshot)





class WgetPlugin(BasePlugin):
    app_label: str = 'wget'
    verbose_name: str = 'WGET'
    
    hooks: List[InstanceOf[BaseHook]] = []


PLUGIN = WgetPlugin()
DJANGO_APP = PLUGIN.AppConfig
