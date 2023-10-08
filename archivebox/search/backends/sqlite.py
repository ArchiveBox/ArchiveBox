from typing import List, Generator

from archivebox.util import enforce_types

@enforce_types
def index(snapshot_id: str, texts: List[str]):
    pass

@enforce_types
def search(text: str) -> List[str]:
    pass

@enforce_types
def flush(snapshot_ids: Generator[str, None, None]):
    pass
