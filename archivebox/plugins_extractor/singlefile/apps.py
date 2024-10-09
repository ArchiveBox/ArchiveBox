__package__ = 'archivebox.plugins_extractor.singlefile'

from pathlib import Path
from typing import List, Dict, Optional
# from typing_extensions import Self

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field
from pydantic_pkgr import BinProvider, BinProviderName, ProviderLookupDict, BinName, bin_abspath, ShallowBinary

# Depends on other Django apps:
from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_binary import BaseBinary, env
from abx.archivebox.base_extractor import BaseExtractor
from abx.archivebox.base_queue import BaseQueue
from abx.archivebox.base_hook import BaseHook

# Depends on Other Plugins:
from archivebox.config.common import ARCHIVING_CONFIG
from plugins_pkg.npm.apps import SYS_NPM_BINPROVIDER, LIB_NPM_BINPROVIDER

###################### Config ##########################

class SinglefileConfig(BaseConfigSet):
    SAVE_SINGLEFILE: bool = True

    SINGLEFILE_USER_AGENT: str              = Field(default=lambda: ARCHIVING_CONFIG.USER_AGENT)
    SINGLEFILE_TIMEOUT: int                 = Field(default=lambda: ARCHIVING_CONFIG.TIMEOUT)
    SINGLEFILE_CHECK_SSL_VALIDITY: bool     = Field(default=lambda: ARCHIVING_CONFIG.CHECK_SSL_VALIDITY)
    SINGLEFILE_COOKIES_FILE: Optional[Path] = Field(default=lambda: ARCHIVING_CONFIG.COOKIES_FILE)

    SINGLEFILE_BINARY: str = Field(default='single-file')
    SINGLEFILE_EXTRA_ARGS: List[str] = []


SINGLEFILE_CONFIG = SinglefileConfig()


SINGLEFILE_MIN_VERSION = '1.1.54'
SINGLEFILE_MAX_VERSION = '1.1.60'


class SinglefileBinary(BaseBinary):
    name: BinName = SINGLEFILE_CONFIG.SINGLEFILE_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER, env]

    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        LIB_NPM_BINPROVIDER.name: {
            "abspath": lambda:
                bin_abspath(SINGLEFILE_CONFIG.SINGLEFILE_BINARY, PATH=LIB_NPM_BINPROVIDER.PATH)
                or bin_abspath("single-file", PATH=LIB_NPM_BINPROVIDER.PATH)
                or bin_abspath("single-file-node.js", PATH=LIB_NPM_BINPROVIDER.PATH),
            "packages": lambda:
                [f"single-file-cli@>={SINGLEFILE_MIN_VERSION} <{SINGLEFILE_MAX_VERSION}"],
        },
        SYS_NPM_BINPROVIDER.name: {
            "abspath": lambda:
                bin_abspath(SINGLEFILE_CONFIG.SINGLEFILE_BINARY, PATH=SYS_NPM_BINPROVIDER.PATH)
                or bin_abspath("single-file", PATH=SYS_NPM_BINPROVIDER.PATH)
                or bin_abspath("single-file-node.js", PATH=SYS_NPM_BINPROVIDER.PATH),
            "packages": lambda:
                [],    # prevent modifying system global npm packages
        },
        env.name: {
            'abspath': lambda:
                bin_abspath(SINGLEFILE_CONFIG.SINGLEFILE_BINARY, PATH=env.PATH)
                or bin_abspath('single-file', PATH=env.PATH)
                or bin_abspath('single-file-node.js', PATH=env.PATH),
        },
    }
    
    def install(self, binprovider_name: Optional[BinProviderName]=None, **kwargs) -> ShallowBinary:
        # force install to only use lib/npm provider, we never want to modify global NPM packages
        return BaseBinary.install(self, binprovider_name=binprovider_name or LIB_NPM_BINPROVIDER.name, **kwargs)
    
    def load_or_install(self, binprovider_name: Optional[BinProviderName]=None, fresh=False, **kwargs) -> ShallowBinary:
        try:
            return self.load(fresh=fresh)
        except Exception:
            # force install to only use lib/npm provider, we never want to modify global NPM packages
            return BaseBinary.install(self, binprovider_name=binprovider_name or LIB_NPM_BINPROVIDER.name, **kwargs)



SINGLEFILE_BINARY = SinglefileBinary()

PLUGIN_BINARIES = [SINGLEFILE_BINARY]

class SinglefileExtractor(BaseExtractor):
    name: str = 'singlefile'
    binary: BinName = SINGLEFILE_BINARY.name

    def get_output_path(self, snapshot) -> Path:
        return Path(snapshot.link_dir) / 'singlefile.html'


SINGLEFILE_BINARY = SinglefileBinary()
SINGLEFILE_EXTRACTOR = SinglefileExtractor()

class SinglefileQueue(BaseQueue):
    name: str = 'singlefile'
    
    binaries: List[InstanceOf[BaseBinary]] = [SINGLEFILE_BINARY]

SINGLEFILE_QUEUE = SinglefileQueue()

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
# PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
