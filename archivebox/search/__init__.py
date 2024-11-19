__package__ = 'archivebox.search'

from pathlib import Path
from typing import List, Union

from django.db.models import QuerySet
from django.conf import settings

import abx
import archivebox
from archivebox.index.schema import Link
from archivebox.misc.util import enforce_types
from archivebox.misc.logging import stderr
from archivebox.config.common import SEARCH_BACKEND_CONFIG


def log_index_started(url):
    print('[green][*] Indexing url: {} in the search index[/]'.format(url))
    print( )

def get_file_result_content(res, extra_path, use_pwd=False):
    if use_pwd: 
        fpath = f'{res.pwd}/{res.output}'
    else:
        fpath = f'{res.output}'
    
    if extra_path:
        fpath = f'{fpath}/{extra_path}'

    with open(fpath, 'r', encoding='utf-8') as file:
        data = file.read()
    if data:
        return [data]
    return []


# TODO: This should be abstracted by a plugin interface for extractors
@enforce_types
def get_indexable_content(results: QuerySet):
    if not results:
        return []
    # Only use the first method available
    res, method = results.first(), results.first().extractor
    if method not in ('readability', 'singlefile', 'dom', 'wget'):
        return []
    # This should come from a plugin interface

    # TODO: banish this duplication and get these from the extractor file
    if method == 'readability':
        return get_file_result_content(res, 'content.txt', use_pwd=True)
    elif method == 'singlefile':
        return get_file_result_content(res, '', use_pwd=True)
    elif method == 'dom':
        return get_file_result_content(res, '', use_pwd=True)
    elif method == 'wget':
        return get_file_result_content(res, '', use_pwd=True)


def import_backend():
    for backend in abx.as_dict(archivebox.pm.hook.get_SEARCHBACKENDS()).values():
        if backend.name == SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_ENGINE:
            return backend
    raise Exception(f'Could not load {SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_ENGINE} as search backend')

@enforce_types
def write_search_index(link: Link, texts: Union[List[str], None]=None, out_dir: Path=settings.DATA_DIR, skip_text_index: bool=False) -> None:
    if not SEARCH_BACKEND_CONFIG.USE_INDEXING_BACKEND:
        return

    if not skip_text_index and texts:
        from core.models import Snapshot

        snap = Snapshot.objects.filter(url=link.url).first()
        backend = import_backend()
        if snap:
            try:
                backend.index(snapshot_id=str(snap.pk), texts=texts)
            except Exception as err:
                stderr()
                stderr(
                    f'[X] The search backend threw an exception={err}:',
                color='red',
                )

@enforce_types
def query_search_index(query: str, out_dir: Path=settings.DATA_DIR) -> QuerySet:
    from core.models import Snapshot

    if SEARCH_BACKEND_CONFIG.USE_SEARCHING_BACKEND:
        backend = import_backend()
        try:
            snapshot_pks = backend.search(query)
        except Exception as err:
            stderr()
            stderr(
                    f'[X] The search backend threw an exception={err}:',
                color='red',
                )
            raise
        else:
            # TODO preserve ordering from backend
            qsearch = Snapshot.objects.filter(pk__in=snapshot_pks)
            return qsearch
    
    return Snapshot.objects.none()

@enforce_types
def flush_search_index(snapshots: QuerySet):
    if not SEARCH_BACKEND_CONFIG.USE_INDEXING_BACKEND or not snapshots:
        return
    backend = import_backend()
    snapshot_pks = (str(pk) for pk in snapshots.values_list('pk', flat=True))
    try:
        backend.flush(snapshot_pks)
    except Exception as err:
        stderr()
        stderr(
            f'[X] The search backend threw an exception={err}:',
        color='red',
        )

@enforce_types
def index_links(links: Union[List[Link],None], out_dir: Path=settings.DATA_DIR):
    if not links:
        return

    from core.models import Snapshot, ArchiveResult

    for link in links:
        snap = Snapshot.objects.filter(url=link.url).first()
        if snap: 
            results = ArchiveResult.objects.indexable().filter(snapshot=snap)
            log_index_started(link.url)
            try:
                texts = get_indexable_content(results)
            except Exception as err:
                stderr()
                stderr(
                    f'[X] An Exception ocurred reading the indexable content={err}:',
                    color='red',
                    ) 
            else:
                write_search_index(link, texts, out_dir=out_dir)
