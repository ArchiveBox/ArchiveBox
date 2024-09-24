from typing import List, Union
from pathlib import Path

from django.db.models import QuerySet
from django.conf import settings

from archivebox.index.schema import Link
from archivebox.util import enforce_types
from archivebox.config import stderr

# from archivebox.plugins_sys.config.apps import settings.CONFIGS.SearchBackendConfig

from .utils import get_indexable_content, log_index_started


def import_backend():
    for backend in settings.SEARCH_BACKENDS:
        if backend.name == settings.CONFIGS.SearchBackendConfig.SEARCH_BACKEND_ENGINE:
            return backend
    raise Exception(f'Could not load {settings.CONFIGS.SearchBackendConfig.SEARCH_BACKEND_ENGINE} as search backend')

@enforce_types
def write_search_index(link: Link, texts: Union[List[str], None]=None, out_dir: Path=settings.DATA_DIR, skip_text_index: bool=False) -> None:
    if not settings.CONFIGS.SearchBackendConfig.USE_INDEXING_BACKEND:
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

    if settings.CONFIGS.SearchBackendConfig.USE_SEARCHING_BACKEND:
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
    if not settings.CONFIGS.SearchBackendConfig.USE_INDEXING_BACKEND or not snapshots:
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
