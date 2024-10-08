__package__ = 'archivebox.plugins_search.ripgrep'

import re
from pathlib import Path
from subprocess import run
from typing import List, Dict, Iterable
# from typing_extensions import Self

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field
from pydantic_pkgr import BinProvider, BinProviderName, ProviderLookupDict, BinName

# Depends on other Django apps:
from abx.archivebox.base_plugin import BasePlugin
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_binary import BaseBinary, env, apt, brew
from abx.archivebox.base_hook import BaseHook
from abx.archivebox.base_searchbackend import BaseSearchBackend

# Depends on Other Plugins:
from archivebox.config import CONSTANTS
from archivebox.config.common import SEARCH_BACKEND_CONFIG

###################### Config ##########################

class RipgrepConfig(BaseConfigSet):
    RIPGREP_BINARY: str = Field(default='rg')
    
    RIPGREP_IGNORE_EXTENSIONS: str = Field(default='css,js,orig,svg')
    RIPGREP_ARGS_DEFAULT: List[str] = Field(default=lambda c: [
        # https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md
        f'--type-add=ignore:*.{{{c.RIPGREP_IGNORE_EXTENSIONS}}}',
        '--type-not=ignore',
        '--ignore-case',
        '--files-with-matches',
        '--regexp',
    ])
    RIPGREP_SEARCH_DIR: Path = CONSTANTS.ARCHIVE_DIR

RIPGREP_CONFIG = RipgrepConfig()



class RipgrepBinary(BaseBinary):
    name: BinName = RIPGREP_CONFIG.RIPGREP_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        apt.name: {'packages': lambda: ['ripgrep']},
        brew.name: {'packages': lambda: ['ripgrep']},
    }

RIPGREP_BINARY = RipgrepBinary()

# regex to match archive/<ts>/... snapshot dir names
TIMESTAMP_REGEX =  re.compile(r'\/([\d]+\.[\d]+)\/')

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
        from core.models import Snapshot
        
        ripgrep_binary = RIPGREP_BINARY.load()
        if not ripgrep_binary.version:
            raise Exception("ripgrep binary not found, install ripgrep to use this search backend")
    
        cmd = [
            ripgrep_binary.abspath, 
            *RIPGREP_CONFIG.RIPGREP_ARGS_DEFAULT,
            text,
            str(RIPGREP_CONFIG.RIPGREP_SEARCH_DIR),
        ]
        proc = run(cmd, timeout=SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_TIMEOUT, capture_output=True, text=True)
        timestamps = set()
        for path in proc.stdout.splitlines():
            ts = TIMESTAMP_REGEX.findall(path)
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
# PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
