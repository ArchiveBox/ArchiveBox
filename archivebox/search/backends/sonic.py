from typing import List

from sonic import IngestClient, SearchClient

from archivebox.util import enforce_types

@enforce_types
def index(snapshot_id: str, texts: List[str]):
    # TODO add variables to localhost, port, password, bucket, collection
    with IngestClient("localhost", 1491, "SecretPassword") as ingestcl:
        for text in texts:
            ingestcl.push("archivebox", "snapshots", snapshot_id, str(text))

@enforce_types
def search(text: str) -> List:
    with SearchClient("localhost", 1491, "SecretPassword") as querycl:
        snap_ids = querycl.query("archivebox", "snapshots", text)
    return snap_ids
    