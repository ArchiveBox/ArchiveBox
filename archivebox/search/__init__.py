from typing import List, Optional, Union
from pathlib import Path

from sonic import IngestClient, SearchClient

from ..index.schema import Link, ArchiveResult
from ..util import enforce_types
from ..config import setup_django, OUTPUT_DIR


@enforce_types
def write_sonic_index(snapshot_id: str, texts: List[str]):
    # TODO add variables to localhost, port, password, bucket, collection
    with IngestClient("localhost", 1491, "SecretPassword") as ingestcl:
        for text in texts:
            ingestcl.push("archivebox", "snapshots", snapshot_id, str(text))

@enforce_types
def search_sonic_index(text: str) -> List:
    with SearchClient("localhost", 1491, "SecretPassword") as querycl:
        snap_ids = querycl.query("archivebox", "snapshots", text)
    return snap_ids


@enforce_types
def search_index(text: str) -> List:
    # get backend
    return search_sonic_index(text)


@enforce_types
def write_search_index(link: Link, texts: Union[List[str], None]=None, out_dir: Path=OUTPUT_DIR, skip_text_index: bool=False) -> None:
    setup_django(out_dir, check_db=True)
    from core.models import Snapshot

    if not skip_text_index and texts:
        snap = Snapshot.objects.filter(url=link.url).first()
        if snap:
            # get backend
            write_sonic_index(str(snap.id), texts)