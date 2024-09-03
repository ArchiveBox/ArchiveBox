from pathlib import Path
from typing import List, Dict, Optional

from django.apps import AppConfig

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field
from pydantic_pkgr import BinProvider, BinProviderName, ProviderLookupDict, BinName
from pydantic_pkgr.binprovider import bin_abspath

# Depends on other Django apps:
from plugantic.base_plugin import BasePlugin, BaseConfigSet, BaseBinary, BaseExtractor, BaseReplayer
from plugantic.base_configset import ConfigSectionName

# Depends on Other Plugins:
from pkg.settings import env
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

SINGLEFILE_CONFIGS = [
    SinglefileToggleConfigs(**DEFAULT_GLOBAL_CONFIG),
    SinglefileDependencyConfigs(**DEFAULT_GLOBAL_CONFIG),
    SinglefileOptionsConfigs(**DEFAULT_GLOBAL_CONFIG),
]



min_version: str = "1.1.54"
max_version: str = "2.0.0"

def get_singlefile_abspath() -> Optional[Path]:
    return 


class SinglefileBinary(BaseBinary):
    name: BinName = 'single-file'
    binproviders_supported: List[InstanceOf[BinProvider]] = [env, npm]

    provider_overrides: Dict[BinProviderName, ProviderLookupDict] ={
        # 'env': {
        #     'abspath': lambda: bin_abspath('single-file-node.js', PATH=env.PATH) or bin_abspath('single-file', PATH=env.PATH),
        # },
        # 'npm': {
        #     'abspath': lambda: bin_abspath('single-file', PATH=npm.PATH) or bin_abspath('single-file-node.js', PATH=npm.PATH),
        #     'subdeps': lambda: f'single-file-cli@>={min_version} <{max_version}',
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
    name: str = 'builtin_plugins.singlefile'
    app_label: str ='singlefile'
    verbose_name: str = 'SingleFile'

    configs: List[InstanceOf[BaseConfigSet]] = SINGLEFILE_CONFIGS
    binaries: List[InstanceOf[BaseBinary]] = [SINGLEFILE_BINARY]
    extractors: List[InstanceOf[BaseExtractor]] = [SINGLEFILE_EXTRACTOR]



PLUGIN = SinglefilePlugin()
DJANGO_APP = PLUGIN.AppConfig
# CONFIGS = PLUGIN.configs
# BINARIES = PLUGIN.binaries
# EXTRACTORS = PLUGIN.extractors
# REPLAYERS = PLUGIN.replayers
# CHECKS = PLUGIN.checks
