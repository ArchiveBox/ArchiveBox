__package__ = 'abx_plugin_sonic_search'

from typing import List, Generator, cast

from abx_spec_searchbackend import BaseSearchBackend


from .config import SONIC_CONFIG, SONIC_LIB


class SonicSearchBackend(BaseSearchBackend):
    name: str = 'sonic'
    docs_url: str = 'https://github.com/valeriansaliou/sonic'
    
    @staticmethod
    def index(snapshot_id: str, texts: List[str]):
        error_count = 0
        with SONIC_LIB.IngestClient(SONIC_CONFIG.SONIC_HOST, str(SONIC_CONFIG.SONIC_PORT), SONIC_CONFIG.SONIC_PASSWORD) as ingestcl:
            for text in texts:
                chunks = (
                    text[i:i+SONIC_CONFIG.SONIC_MAX_CHUNK_LENGTH]
                    for i in range(
                        0,
                        min(len(text), SONIC_CONFIG.SONIC_MAX_TEXT_LENGTH),
                        SONIC_CONFIG.SONIC_MAX_CHUNK_LENGTH,
                    )
                )
                try:
                    for chunk in chunks:
                        ingestcl.push(SONIC_CONFIG.SONIC_COLLECTION, SONIC_CONFIG.SONIC_BUCKET, snapshot_id, str(chunk))
                except Exception as err:
                    print(f'[!] Sonic search backend threw an error while indexing: {err.__class__.__name__} {err}')
                    error_count += 1
                    if error_count > SONIC_CONFIG.SONIC_MAX_RETRIES:
                        raise

    @staticmethod
    def flush(snapshot_ids: Generator[str, None, None]):
        with SONIC_LIB.IngestClient(SONIC_CONFIG.SONIC_HOST, str(SONIC_CONFIG.SONIC_PORT), SONIC_CONFIG.SONIC_PASSWORD) as ingestcl:
            for id in snapshot_ids:
                ingestcl.flush_object(SONIC_CONFIG.SONIC_COLLECTION, SONIC_CONFIG.SONIC_BUCKET, str(id))
    

    @staticmethod
    def search(text: str) -> List[str]:
        with SONIC_LIB.SearchClient(SONIC_CONFIG.SONIC_HOST, SONIC_CONFIG.SONIC_PORT, SONIC_CONFIG.SONIC_PASSWORD) as querycl:
            snap_ids = cast(List[str], querycl.query(SONIC_CONFIG.SONIC_COLLECTION, SONIC_CONFIG.SONIC_BUCKET, text))
        return [str(id) for id in snap_ids]
    
    
SONIC_SEARCH_BACKEND = SonicSearchBackend()
