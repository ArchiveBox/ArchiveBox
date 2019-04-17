import os
import json

from datetime import datetime
from typing import List, Optional, Iterator

from ..schema import Link, ArchiveResult
from ..config import (
    VERSION,
    OUTPUT_DIR,
)
from ..util import (
    enforce_types,
    atomic_write,
)


### Main Links Index

@enforce_types
def parse_json_main_index(out_dir: str=OUTPUT_DIR) -> Iterator[Link]:
    """parse a archive index json file and return the list of links"""

    index_path = os.path.join(out_dir, 'index.json')
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            links = json.load(f)['links']
            for link_json in links:
                yield Link.from_json(link_json)

    return ()

@enforce_types
def write_json_main_index(links: List[Link], out_dir: str=OUTPUT_DIR) -> None:
    """write the json link index to a given path"""

    assert isinstance(links, List), 'Links must be a list, not a generator.'
    assert not links or isinstance(links[0].history, dict)
    assert not links or isinstance(links[0].sources, list)

    if links and links[0].history.get('title'):
        assert isinstance(links[0].history['title'][0], ArchiveResult)

    if links and links[0].sources:
        assert isinstance(links[0].sources[0], str)

    path = os.path.join(out_dir, 'index.json')

    index_json = {
        'info': 'ArchiveBox Index',
        'source': 'https://github.com/pirate/ArchiveBox',
        'docs': 'https://github.com/pirate/ArchiveBox/wiki',
        'version': VERSION,
        'num_links': len(links),
        'updated': datetime.now(),
        'links': links,
    }
    atomic_write(index_json, path)


### Link Details Index

@enforce_types
def write_json_link_details(link: Link, out_dir: Optional[str]=None) -> None:
    """write a json file with some info about the link"""
    
    out_dir = out_dir or link.link_dir
    path = os.path.join(out_dir, 'index.json')

    atomic_write(link._asdict(extended=True), path)


@enforce_types
def parse_json_link_details(out_dir: str) -> Optional[Link]:
    """load the json link index from a given directory"""
    existing_index = os.path.join(out_dir, 'index.json')
    if os.path.exists(existing_index):
        with open(existing_index, 'r', encoding='utf-8') as f:
            link_json = json.load(f)
            return Link.from_json(link_json)
    return None
