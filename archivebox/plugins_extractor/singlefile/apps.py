__package__ = 'archivebox.plugins_extractor.singlefile'

from pathlib import Path
from typing import List, Dict, Optional, ClassVar
# from typing_extensions import Self

from django.conf import settings

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field, validate_call
from pydantic_pkgr import BinProvider, BinProviderName, ProviderLookupDict, BinName, bin_abspath, ShallowBinary

# Depends on other Django apps:
from plugantic.base_plugin import BasePlugin
from plugantic.base_configset import BaseConfigSet, ConfigSectionName
from plugantic.base_binary import BaseBinary, env
from plugantic.base_extractor import BaseExtractor
from plugantic.base_queue import BaseQueue
from plugantic.base_hook import BaseHook

# Depends on Other Plugins:
from plugins_sys.config.apps import ARCHIVING_CONFIG
from plugins_pkg.npm.apps import SYS_NPM_BINPROVIDER, LIB_NPM_BINPROVIDER

###################### Config ##########################

class SinglefileConfig(BaseConfigSet):
    section: ClassVar[ConfigSectionName] = 'ARCHIVING_CONFIG'

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
        env.name: {
            'abspath': lambda:
                bin_abspath(SINGLEFILE_CONFIG.SINGLEFILE_BINARY, PATH=env.PATH)
                or bin_abspath('single-file', PATH=env.PATH)
                or bin_abspath('single-file-node.js', PATH=env.PATH),
        },
        LIB_NPM_BINPROVIDER.name: {
            "abspath": lambda:
                bin_abspath(SINGLEFILE_CONFIG.SINGLEFILE_BINARY, PATH=env.PATH)
                or bin_abspath("single-file", PATH=LIB_NPM_BINPROVIDER.PATH)
                or bin_abspath("single-file-node.js", PATH=LIB_NPM_BINPROVIDER.PATH),
            "packages": lambda:
                [f"single-file-cli@>={SINGLEFILE_MIN_VERSION} <{SINGLEFILE_MAX_VERSION}"],
        },
        SYS_NPM_BINPROVIDER.name: {
            "packages": lambda:
                [],    # prevent modifying system global npm packages
        },
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


# ALTERNATIVE INSTALL METHOD using Ansible:
# install_playbook = PLUGANTIC_DIR / 'ansible' / 'install_singlefile.yml'
# singlefile_bin = run_playbook(install_playbook, data_dir=settings.CONFIG.OUTPUT_DIR, quiet=quiet).BINARIES.singlefile
# return self.__class__.model_validate(
#     {
#         **self.model_dump(),
#         "loaded_abspath": singlefile_bin.abspath,
#         "loaded_version": singlefile_bin.version,
#         "loaded_binprovider": env,
#         "binproviders_supported": self.binproviders_supported,
#     }
# )


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
