#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox extract'


import sys
from typing import TYPE_CHECKING, Generator

import rich_click as click

from django.db.models import Q

from archivebox.misc.util import enforce_types, docstring


if TYPE_CHECKING:
    from core.models import ArchiveResult


ORCHESTRATOR = None

@enforce_types
def extract(archiveresult_id: str) -> Generator['ArchiveResult', None, None]:
    archiveresult = ArchiveResult.objects.get(Q(id=archiveresult_id) | Q(abid=archiveresult_id))
    if not archiveresult:
        raise Exception(f'ArchiveResult {archiveresult_id} not found')
    
    return archiveresult.EXTRACTOR.extract()

# <user>@<machine_id>#<datetime>/absolute/path/to/binary
# 2014.24.01

@click.command()

@click.argument('archiveresult_ids', nargs=-1, type=str)
@docstring(extract.__doc__)
def main(archiveresult_ids: list[str]):
    """Add a new URL or list of URLs to your archive"""
    
    for archiveresult_id in (archiveresult_ids or sys.stdin):
        print(f'Extracting {archiveresult_id}...')
        archiveresult = extract(str(archiveresult_id))
        print(archiveresult.as_json())


if __name__ == '__main__':
    main()

