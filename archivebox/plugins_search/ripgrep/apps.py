__package__ = 'archivebox.plugins_search.ripgrep'

import re
from subprocess import run
from typing import List, Dict, ClassVar, Iterable
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
from plugantic.base_searchbackend import BaseSearchBackend

# Depends on Other Plugins:
from plugins_sys.config.apps import SEARCH_BACKEND_CONFIG

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


RG_IGNORE_EXTENSIONS = ('css','js','orig','svg')

RG_ADD_TYPE = '--type-add'
RG_IGNORE_ARGUMENTS = f"ignore:*.{{{','.join(RG_IGNORE_EXTENSIONS)}}}"
RG_DEFAULT_ARGUMENTS = "-ilTignore" # Case insensitive(i), matching files results(l)
RG_REGEX_ARGUMENT = '-e'

TIMESTAMP_REGEX = r'\/([\d]+\.[\d]+)\/'
ts_regex =  re.compile(TIMESTAMP_REGEX)


class RipgrepSearchBackend(BaseSearchBackend):
    name: str = 'ripgrep'
    docs_url: str = 'https://github.com/BurntSushi/ripgrep'
    
    @staticmethod
    def index(snapshot_id: str, texts: List[str]):
        return

    @staticmethod
    def flush(snapshot_ids: Iterable[str]):
        return

    @staticmethod
    def search(text: str) -> List[str]:
        rg_bin = RIPGREP_BINARY.load()
        if not rg_bin.version:
            raise Exception("ripgrep binary not found, install ripgrep to use this search backend")
    
        rg_cmd = [
            rg_bin.abspath, 
            RG_ADD_TYPE, 
            RG_IGNORE_ARGUMENTS, 
            RG_DEFAULT_ARGUMENTS, 
            RG_REGEX_ARGUMENT, 
            text, 
            str(settings.ARCHIVE_DIR)
        ]
        rg = run(rg_cmd, timeout=SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_TIMEOUT, capture_output=True, text=True)
        timestamps = set()
        for path in rg.stdout.splitlines():
            ts = ts_regex.findall(path)
            if ts:
                timestamps.add(ts[0])
        
        snap_ids = [str(id) for id in Snapshot.objects.filter(timestamp__in=timestamps).values_list('pk', flat=True)]
    
        return snap_ids
    
RIPGREP_SEARCH_BACKEND = RipgrepSearchBackend()




class RipgrepSearchPlugin(BasePlugin):
    app_label: str ='ripgrep'
    verbose_name: str = 'Ripgrep'

    hooks: List[InstanceOf[BaseHook]] = [
        RIPGREP_CONFIG,
        RIPGREP_BINARY,
        RIPGREP_SEARCH_BACKEND,
    ]



PLUGIN = RipgrepSearchPlugin()
PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
