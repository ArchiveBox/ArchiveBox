__package__ = 'archivebox.plugins_extractor.readability'

from pathlib import Path
from typing import List, Dict, Optional
# from typing_extensions import Self

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field, validate_call
from pydantic_pkgr import BinProvider, BinProviderName, ProviderLookupDict, BinName, ShallowBinary

# Depends on other Django apps:
from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_binary import BaseBinary, env
from abx.archivebox.base_extractor import BaseExtractor
from abx.archivebox.base_hook import BaseHook

# Depends on Other Plugins:
from archivebox.config.common import ARCHIVING_CONFIG
from plugins_pkg.npm.apps import SYS_NPM_BINPROVIDER, LIB_NPM_BINPROVIDER

###################### Config ##########################

class ReadabilityConfig(BaseConfigSet):
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
    def install(self, binprovider_name: Optional[BinProviderName]=None, **kwargs) -> ShallowBinary:
        # force install to only use lib/npm provider, we never want to modify global NPM packages
        return BaseBinary.install(self, binprovider_name=binprovider_name or LIB_NPM_BINPROVIDER.name, **kwargs)
    
    @validate_call
    def load_or_install(self, binprovider_name: Optional[BinProviderName] = None, fresh=False, **kwargs) -> ShallowBinary:
        try:
            return self.load(fresh=fresh)
        except Exception:
            # force install to only use lib/npm provider, we never want to modify global NPM packages
            return BaseBinary.install(self, binprovider_name=binprovider_name or LIB_NPM_BINPROVIDER.name, **kwargs)




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
    app_label: str ='readability'
    verbose_name: str = 'Readability'

    hooks: List[InstanceOf[BaseHook]] = [
        READABILITY_CONFIG,
        READABILITY_BINARY,
        READABILITY_EXTRACTOR,
        # READABILITY_QUEUE,
    ]



PLUGIN = ReadabilityPlugin()
# PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
