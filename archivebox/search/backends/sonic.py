from typing import List

from sonic import IngestClient, SearchClient

from archivebox.util import enforce_types
from archivebox.config import SEARCH_BACKEND_HOST_NAME, SEARCH_BACKEND_PORT, SEARCH_BACKEND_PASSWORD, SONIC_BUCKET, SONIC_COLLECTION


@enforce_types
def index(snapshot_id: str, texts: List[str]):
    with IngestClient(SEARCH_BACKEND_HOST_NAME, SEARCH_BACKEND_PORT, SEARCH_BACKEND_PASSWORD) as ingestcl:
        for text in texts:
            ingestcl.push(SONIC_COLLECTION, SONIC_BUCKET, snapshot_id, str(text))

@enforce_types
def search(text: str) -> List:
    with SearchClient(SEARCH_BACKEND_HOST_NAME, SEARCH_BACKEND_PORT, SEARCH_BACKEND_PASSWORD) as querycl:
        snap_ids = querycl.query(SONIC_COLLECTION, SONIC_BUCKET, text)
    return snap_ids

@enforce_types
def flush(snapshot_ids: List[str]):
    with IngestClient(SEARCH_BACKEND_HOST_NAME, SEARCH_BACKEND_PORT, SEARCH_BACKEND_PASSWORD) as ingestcl:
        for id in snapshot_ids:
            ingestcl.flush_object(SONIC_COLLECTION, SONIC_BUCKET, str(id))
