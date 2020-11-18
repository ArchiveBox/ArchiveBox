from typing import List, Union
from pathlib import Path
from importlib import import_module


from archivebox.index.schema import Link
from archivebox.util import enforce_types
from archivebox.config import setup_django, OUTPUT_DIR


def indexing_enabled():
    return True
    # return FULLTEXT_INDEXING_ENABLED

def search_backend_enabled():
    return True
    # return FULLTEXT_SEARCH_ENABLED

def get_backend():
    return 'search.backends.sonic'

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
def query_search_index(text: str) -> List:
    if search_backend_enabled():
        backend = import_backend()
        return backend.search(text)
    else:
        return []
        