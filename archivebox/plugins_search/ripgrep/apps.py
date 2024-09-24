__package__ = 'archivebox.plugins_search.ripgrep'

from typing import List, Dict, ClassVar
# from typing_extensions import Self

from django.conf import settings

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field
from pydantic_pkgr import BinProvider, BinProviderName, ProviderLookupDict, BinName

# Depends on other Django apps:
from plugantic.base_plugin import BasePlugin
from plugantic.base_configset import BaseConfigSet, ConfigSectionName
from plugantic.base_binary import BaseBinary, env, apt, brew
from plugantic.base_hook import BaseHook
# from plugantic.base_search import BaseSearchBackend

# Depends on Other Plugins:
# from plugins_sys.config.apps import SEARCH_BACKEND_CONFIG

###################### Config ##########################

class RipgrepConfig(BaseConfigSet):
    section: ClassVar[ConfigSectionName] = 'DEPENDENCY_CONFIG'

    RIPGREP_BINARY: str = Field(default='rg')

RIPGREP_CONFIG = RipgrepConfig()

class RipgrepBinary(BaseBinary):
    name: BinName = RIPGREP_CONFIG.RIPGREP_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        apt.name: {'packages': lambda: ['ripgrep']},
        brew.name: {'packages': lambda: ['ripgrep']},
    }

RIPGREP_BINARY = RipgrepBinary()

# TODO:
# class RipgrepSearchBackend(BaseSearchBackend):
#     name: str = 'ripgrep'

# RIPGREP_SEARCH_BACKEND = RipgrepSearchBackend()


class RipgrepSearchPlugin(BasePlugin):
    app_label: str ='ripgrep'
    verbose_name: str = 'Ripgrep'

    hooks: List[InstanceOf[BaseHook]] = [
        RIPGREP_CONFIG,
        RIPGREP_BINARY,
    ]



PLUGIN = RipgrepSearchPlugin()
PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
