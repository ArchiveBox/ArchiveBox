from typing import List, Union, Generator
from pathlib import Path
from importlib import import_module


from archivebox.index.schema import Link
from archivebox.util import enforce_types
from archivebox.config import setup_django, OUTPUT_DIR, USE_INDEXING_BACKEND, USE_SEARCHING_BACKEND, SEARCH_BACKEND_ENGINE

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
            backend.index(snapshot_id=str(snap.id), texts=texts)

@enforce_types
def query_search_index(text: str) -> List[str]:  
    if search_backend_enabled():
        backend = import_backend()
        return backend.search(text)
    else:
        return []

@enforce_types
def flush_search_index(snapshot_ids: Generator[str, None, None]):
    if not indexing_enabled() or not snapshot_ids:
        return
    backend = import_backend()
    backend.flush(snapshot_ids)
