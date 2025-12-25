"""
Sonic search backend - search and flush operations.

This module provides the search interface for the Sonic backend.
"""

import os
from typing import List, Iterable


def get_sonic_config() -> dict:
    """Get Sonic connection configuration."""
    return {
        'host': os.environ.get('SEARCH_BACKEND_HOST_NAME', '127.0.0.1').strip(),
        'port': int(os.environ.get('SEARCH_BACKEND_PORT', '1491')),
        'password': os.environ.get('SEARCH_BACKEND_PASSWORD', 'SecretPassword').strip(),
        'collection': os.environ.get('SONIC_COLLECTION', 'archivebox').strip(),
        'bucket': os.environ.get('SONIC_BUCKET', 'snapshots').strip(),
    }


def search(query: str) -> List[str]:
    """Search for snapshots in Sonic."""
    try:
        from sonic import SearchClient
    except ImportError:
        raise RuntimeError('sonic-client not installed. Run: pip install sonic-client')

    config = get_sonic_config()

    with SearchClient(config['host'], config['port'], config['password']) as search_client:
        results = search_client.query(config['collection'], config['bucket'], query, limit=100)
        return results


def flush(snapshot_ids: Iterable[str]) -> None:
    """Remove snapshots from Sonic index."""
    try:
        from sonic import IngestClient
    except ImportError:
        raise RuntimeError('sonic-client not installed. Run: pip install sonic-client')

    config = get_sonic_config()

    with IngestClient(config['host'], config['port'], config['password']) as ingest:
        for snapshot_id in snapshot_ids:
            try:
                ingest.flush_object(config['collection'], config['bucket'], snapshot_id)
            except Exception:
                pass
