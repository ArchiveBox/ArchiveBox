from typing import List, Union
from pathlib import Path
from importlib import import_module

from django.db.models import QuerySet

from archivebox.index.schema import Link
from archivebox.util import enforce_types
from archivebox.config import setup_django,stderr, OUTPUT_DIR, USE_INDEXING_BACKEND, USE_SEARCHING_BACKEND, SEARCH_BACKEND_ENGINE

from .utils import get_indexable_content, log_index_started

def indexing_enabled():
    return USE_INDEXING_BACKEND

def search_backend_enabled():
    return USE_SEARCHING_BACKEND

def get_backend():
    return f'search.backends.{SEARCH_BACKEND_ENGINE}'

def import_backend():
    backend_string = get_backend()
    try:
        backend = import_module(backend_string)
    except Exception as err:
        raise Exception("Could not load '%s' as a backend: %s" % (backend_string, err))
    return backend

@enforce_types
def write_search_index(link: Link, texts: Union[List[str], None]=None, out_dir: Path=OUTPUT_DIR, skip_text_index: bool=False) -> None:
    if not indexing_enabled():
        return

    if not skip_text_index and texts:
        setup_django(out_dir, check_db=True)
        from core.models import Snapshot

        snap = Snapshot.objects.filter(url=link.url).first()
        backend = import_backend()
        if snap:
            try:
                backend.index(snapshot_id=str(snap.id), texts=texts)
            except Exception as err:
                stderr()
                stderr(
                    f'[X] The search backend threw an exception={err}:',
                color='red',
                )

@enforce_types
def query_search_index(query: str, out_dir: Path=OUTPUT_DIR) -> QuerySet:
    setup_django(out_dir, check_db=True)
    from core.models import Snapshot

    if search_backend_enabled():
        backend = import_backend()
        try:
            snapshot_ids = backend.search(query)
        except Exception as err:
            stderr()
            stderr(
                    f'[X] The search backend threw an exception={err}:',
                color='red',
                )
            raise
        else:
            # TODO preserve ordering from backend
            qsearch = Snapshot.objects.filter(pk__in=snapshot_ids)
            return qsearch
    
    return Snapshot.objects.none()

@enforce_types
def flush_search_index(snapshots: QuerySet):
    if not indexing_enabled() or not snapshots:
        return
    backend = import_backend()
    snapshot_ids=(str(pk) for pk in snapshots.values_list('pk',flat=True))
    try:
        backend.flush(snapshot_ids)
    except Exception as err:
        stderr()
        stderr(
            f'[X] The search backend threw an exception={err}:',
        color='red',
        )

@enforce_types
def index_links(links: Union[List[Link],None], out_dir: Path=OUTPUT_DIR):
    if not links:
        return

    setup_django(out_dir=out_dir, check_db=True)
    from core.models import Snapshot, ArchiveResult

    for link in links:
        if snap := Snapshot.objects.filter(url=link.url).first():
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