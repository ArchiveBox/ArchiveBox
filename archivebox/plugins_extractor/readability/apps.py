__package__ = 'archivebox.plugins_extractor.readability'

from pathlib import Path
from typing import List, Dict, Optional, ClassVar
# from typing_extensions import Self

from django.conf import settings

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field, validate_call
from pydantic_pkgr import BinProvider, BinProviderName, ProviderLookupDict, BinName, ShallowBinary

# Depends on other Django apps:
from plugantic.base_plugin import BasePlugin
from plugantic.base_configset import BaseConfigSet, ConfigSectionName
from plugantic.base_binary import BaseBinary, env
from plugantic.base_extractor import BaseExtractor
from plugantic.base_hook import BaseHook

# Depends on Other Plugins:
from plugins_sys.config.apps import ARCHIVING_CONFIG
from plugins_pkg.npm.apps import SYS_NPM_BINPROVIDER, LIB_NPM_BINPROVIDER

###################### Config ##########################

class ReadabilityConfig(BaseConfigSet):
    section: ClassVar[ConfigSectionName] = 'ARCHIVING_CONFIG'

    SAVE_READABILITY: bool = Field(default=True, alias='USE_READABILITY')

    READABILITY_TIMEOUT: int                 = Field(default=lambda: ARCHIVING_CONFIG.TIMEOUT)

    READABILITY_BINARY: str = Field(default='readability-extractor')
    # READABILITY_EXTRA_ARGS: List[str] = []                                # readability-extractor doesn't take any extra args


READABILITY_CONFIG = ReadabilityConfig()


READABILITY_PACKAGE_NAME = 'github:ArchiveBox/readability-extractor'

class ReadabilityBinary(BaseBinary):
    name: BinName = READABILITY_CONFIG.READABILITY_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER, env]

    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        LIB_NPM_BINPROVIDER.name: {"packages": lambda: [READABILITY_PACKAGE_NAME]},
        SYS_NPM_BINPROVIDER.name: {"packages": lambda: []},    # prevent modifying system global npm packages
    }
    
    @validate_call
    def install(self, binprovider_name: Optional[BinProviderName]=None) -> ShallowBinary:
        # force install to only use lib/npm provider, we never want to modify global NPM packages
        return BaseBinary.install(self, binprovider_name=binprovider_name or LIB_NPM_BINPROVIDER.name)
    
    @validate_call
    def load_or_install(self, binprovider_name: Optional[BinProviderName] = None) -> ShallowBinary:
        # force install to only use lib/npm provider, we never want to modify global NPM packages
        try:
            return self.load()
        except Exception:
            return BaseBinary.install(self, binprovider_name=binprovider_name or LIB_NPM_BINPROVIDER.name)




READABILITY_BINARY = ReadabilityBinary()


class ReadabilityExtractor(BaseExtractor):
    name: str = 'readability'
    binary: BinName = READABILITY_BINARY.name

    def get_output_path(self, snapshot) -> Path:
        return Path(snapshot.link_dir) / 'readability' / 'content.html'


READABILITY_BINARY = ReadabilityBinary()
READABILITY_EXTRACTOR = ReadabilityExtractor()

# class ReadabilityQueue(BaseQueue):
#     name: str = 'singlefile'
    
#     binaries: List[InstanceOf[BaseBinary]] = [READABILITY_BINARY]

# READABILITY_QUEUE = ReadabilityQueue()

class ReadabilityPlugin(BasePlugin):
    app_label: str ='singlefile'
    verbose_name: str = 'SingleFile'

    hooks: List[InstanceOf[BaseHook]] = [
        READABILITY_CONFIG,
        READABILITY_BINARY,
        READABILITY_EXTRACTOR,
        # READABILITY_QUEUE,
    ]



PLUGIN = ReadabilityPlugin()
PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
