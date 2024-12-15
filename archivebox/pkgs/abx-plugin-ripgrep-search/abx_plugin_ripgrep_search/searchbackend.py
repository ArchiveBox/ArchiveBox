__package__ = 'abx_plugin_ripgrep_search'

import re
import subprocess

from typing import List, Iterable

from abx_spec_searchbackend import BaseSearchBackend

from .binaries import RIPGREP_BINARY
from .config import RIPGREP_CONFIG



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
        proc = subprocess.run(cmd, timeout=RIPGREP_CONFIG.RIPGREP_TIMEOUT, capture_output=True, text=True)
        timestamps = set()
        for path in proc.stdout.splitlines():
            ts = TIMESTAMP_REGEX.findall(path)
            if ts:
                timestamps.add(ts[0])
        
        snap_ids = [str(id) for id in Snapshot.objects.filter(timestamp__in=timestamps).values_list('pk', flat=True)]
    
        return snap_ids

RIPGREP_SEARCH_BACKEND = RipgrepSearchBackend()
