from pathlib import Path
from typing import List, Dict, Optional

from django.conf import settings

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field
from pydantic_pkgr import BinProvider, BinProviderName, ProviderLookupDict, BinName

# Depends on other Django apps:
from plugantic.base_plugin import BasePlugin
from plugantic.base_configset import BaseConfigSet, ConfigSectionName
from plugantic.base_binary import BaseBinary, env
from plugantic.base_extractor import BaseExtractor
from plugantic.base_hook import BaseHook

# Depends on Other Plugins:
from builtin_plugins.npm.apps import npm


###################### Config ##########################

class SinglefileToggleConfigs(BaseConfigSet):
    section: ConfigSectionName = 'ARCHIVE_METHOD_TOGGLES'

    SAVE_SINGLEFILE: bool = True


class SinglefileOptionsConfigs(BaseConfigSet):
    section: ConfigSectionName = 'ARCHIVE_METHOD_OPTIONS'

    # loaded from shared config
    SINGLEFILE_USER_AGENT: str = Field(default='', alias='USER_AGENT')
    SINGLEFILE_TIMEOUT: int = Field(default=60, alias='TIMEOUT')
    SINGLEFILE_CHECK_SSL_VALIDITY: bool = Field(default=True, alias='CHECK_SSL_VALIDITY')
    SINGLEFILE_RESTRICT_FILE_NAMES: str = Field(default='windows', alias='RESTRICT_FILE_NAMES')
    SINGLEFILE_COOKIES_FILE: Optional[Path] = Field(default=None, alias='COOKIES_FILE')


class SinglefileDependencyConfigs(BaseConfigSet):
    section: ConfigSectionName = 'DEPENDENCY_CONFIG'

    SINGLEFILE_BINARY: str = Field(default='wget')
    SINGLEFILE_ARGS: Optional[List[str]] = Field(default=None)
    SINGLEFILE_EXTRA_ARGS: List[str] = []
    SINGLEFILE_DEFAULT_ARGS: List[str] = ['--timeout={TIMEOUT-10}']

class SinglefileConfigs(SinglefileToggleConfigs, SinglefileOptionsConfigs, SinglefileDependencyConfigs):
    # section: ConfigSectionName = 'ALL_CONFIGS'
    pass

DEFAULT_GLOBAL_CONFIG = {
    'CHECK_SSL_VALIDITY': False,
    'SAVE_SINGLEFILE': True,
    'TIMEOUT': 120,
}

SINGLEFILE_CONFIG = SinglefileConfigs(**DEFAULT_GLOBAL_CONFIG)



min_version: str = "1.1.54"
max_version: str = "2.0.0"

def get_singlefile_abspath() -> Optional[Path]:
    return 


class SinglefileBinary(BaseBinary):
    name: BinName = 'single-file'
    binproviders_supported: List[InstanceOf[BinProvider]] = [npm, env]

    provider_overrides: Dict[BinProviderName, ProviderLookupDict] ={
        # 'env': {
        #     'abspath': lambda: bin_abspath('single-file-node.js', PATH=env.PATH) or bin_abspath('single-file', PATH=env.PATH),
        # },
        # 'npm': {
        #     'abspath': lambda: bin_abspath('single-file', PATH=npm.PATH) or bin_abspath('single-file-node.js', PATH=npm.PATH),
        #     'packages': lambda: f'single-file-cli@>={min_version} <{max_version}',
        # },
    }

SINGLEFILE_BINARY = SinglefileBinary()

PLUGIN_BINARIES = [SINGLEFILE_BINARY]

class SinglefileExtractor(BaseExtractor):
    name: str = 'singlefile'
    binary: BinName = SINGLEFILE_BINARY.name

    def get_output_path(self, snapshot) -> Path:
        return Path(snapshot.link_dir) / 'singlefile.html'


SINGLEFILE_BINARY = SinglefileBinary()
SINGLEFILE_EXTRACTOR = SinglefileExtractor()

class SinglefilePlugin(BasePlugin):
    app_label: str ='singlefile'
    verbose_name: str = 'SingleFile'

    hooks: List[InstanceOf[BaseHook]] = [
        SINGLEFILE_CONFIG,
        SINGLEFILE_BINARY,
        SINGLEFILE_EXTRACTOR,
        SINGLEFILE_QUEUE,
    ]



PLUGIN = SinglefilePlugin()
PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
