import re
from subprocess import run, PIPE
from typing import List, Generator

from archivebox.config import ARCHIVE_DIR, RIPGREP_VERSION, SEARCH_BACKEND_TIMEOUT
from archivebox.util import enforce_types

RG_IGNORE_EXTENSIONS = ('css','js','orig','svg')

RG_ADD_TYPE = '--type-add'
RG_IGNORE_ARGUMENTS = f"ignore:*.{{{','.join(RG_IGNORE_EXTENSIONS)}}}"
RG_DEFAULT_ARGUMENTS = "-ilTignore" # Case insensitive(i), matching files results(l)
RG_REGEX_ARGUMENT = '-e'

TIMESTAMP_REGEX = r'\/([\d]+\.[\d]+)\/'

ts_regex =  re.compile(TIMESTAMP_REGEX)

@enforce_types
def index(snapshot_id: str, texts: List[str]):
    return

@enforce_types
def flush(snapshot_ids: Generator[str, None, None]):
    return

@enforce_types
def search(text: str) -> List[str]:
    if not RIPGREP_VERSION:
        raise Exception("ripgrep binary not found, install ripgrep to use this search backend")

    from core.models import Snapshot

    rg_cmd = ['rg', RG_ADD_TYPE, RG_IGNORE_ARGUMENTS, RG_DEFAULT_ARGUMENTS, RG_REGEX_ARGUMENT, text, str(ARCHIVE_DIR)]
    rg = run(rg_cmd, stdout=PIPE, stderr=PIPE, timeout=SEARCH_BACKEND_TIMEOUT)
    file_paths = [p.decode() for p in rg.stdout.splitlines()]
    timestamps = set()
    for path in file_paths:
        ts = ts_regex.findall(path)
        if ts:
            timestamps.add(ts[0])
    
    snap_ids = [str(id) for id in Snapshot.objects.filter(timestamp__in=timestamps).values_list('pk', flat=True)]

    return snap_ids
