import re
from subprocess import run, PIPE, DEVNULL
from typing import List, Generator

from archivebox.config import setup_django, ARCHIVE_DIR
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
    is_rg_installed = run(['which', 'rg'], stdout=DEVNULL, stderr=DEVNULL)
    if is_rg_installed.returncode:
        raise Exception("ripgrep binary not found, install ripgrep to use this search backend")

    setup_django(check_db=True)
    from core.models import Snapshot

    rg_cmd = ['rg', RG_ADD_TYPE, RG_IGNORE_ARGUMENTS, RG_DEFAULT_ARGUMENTS, RG_REGEX_ARGUMENT, text, str(ARCHIVE_DIR)]
    rg = run(rg_cmd, stdout=PIPE, stderr=PIPE, timeout=60)
    file_paths = [p.decode() for p in rg.stdout.splitlines()]
    timestamps = set()
    for path in file_paths:
        if ts := ts_regex.findall(path):
            timestamps.add(ts[0])
    
    snap_ids = [str(id) for id in Snapshot.objects.filter(timestamp__in=timestamps).values_list('pk', flat=True)]

    return snap_ids

