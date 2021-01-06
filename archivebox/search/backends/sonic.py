from typing import List, Generator

from sonic import IngestClient, SearchClient

from archivebox.util import enforce_types
from archivebox.config import SEARCH_BACKEND_HOST_NAME, SEARCH_BACKEND_PORT, SEARCH_BACKEND_PASSWORD, SONIC_BUCKET, SONIC_COLLECTION

MAX_SONIC_TEXT_LENGTH = 20000

@enforce_types
def index(snapshot_id: str, texts: List[str]):
    with IngestClient(SEARCH_BACKEND_HOST_NAME, SEARCH_BACKEND_PORT, SEARCH_BACKEND_PASSWORD) as ingestcl:
        for text in texts:
            chunks = [text[i:i+MAX_SONIC_TEXT_LENGTH] for i in range(0, len(text), MAX_SONIC_TEXT_LENGTH)]
            for chunk in chunks:
                ingestcl.push(SONIC_COLLECTION, SONIC_BUCKET, snapshot_id, str(chunk))

@enforce_types
def search(text: str) -> List[str]:
    with SearchClient(SEARCH_BACKEND_HOST_NAME, SEARCH_BACKEND_PORT, SEARCH_BACKEND_PASSWORD) as querycl:
        snap_ids = querycl.query(SONIC_COLLECTION, SONIC_BUCKET, text)
    return snap_ids

@enforce_types
def flush(snapshot_ids: Generator[str, None, None]):
    with IngestClient(SEARCH_BACKEND_HOST_NAME, SEARCH_BACKEND_PORT, SEARCH_BACKEND_PASSWORD) as ingestcl:
        for id in snapshot_ids:
            ingestcl.flush_object(SONIC_COLLECTION, SONIC_BUCKET, str(id))
