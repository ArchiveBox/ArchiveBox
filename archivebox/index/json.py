__package__ = 'archivebox.index'

import os
import sys
import json as pyjson
from pathlib import Path

from datetime import datetime, timezone
from typing import List, Optional, Iterator, Any, Union

from .schema import Link
from ..system import atomic_write
from ..util import enforce_types
from ..config import (
    VERSION,
    OUTPUT_DIR,
    FOOTER_INFO,
    DEPENDENCIES,
    JSON_INDEX_FILENAME,
    ARCHIVE_DIR_NAME,
    ANSI
)


MAIN_INDEX_HEADER = {
    'info': 'This is an index of site data archived by ArchiveBox: The self-hosted web archive.',
    'schema': 'archivebox.index.json',
    'copyright_info': FOOTER_INFO,
    'meta': {
        'project': 'ArchiveBox',
        'version': VERSION,
        'git_sha': VERSION,  # not used anymore, but kept for backwards compatibility
        'website': 'https://ArchiveBox.io',
        'docs': 'https://github.com/ArchiveBox/ArchiveBox/wiki',
        'source': 'https://github.com/ArchiveBox/ArchiveBox',
        'issues': 'https://github.com/ArchiveBox/ArchiveBox/issues',
        'dependencies': DEPENDENCIES,
    },
}

@enforce_types
def generate_json_index_from_links(links: List[Link], with_headers: bool):
    if with_headers:
        output = {
            **MAIN_INDEX_HEADER,
            'num_links': len(links),
            'updated': datetime.now(timezone.utc),
            'last_run_cmd': sys.argv,
            'links': links,
        }
    else:
        output = links
    return to_json(output, indent=4, sort_keys=True)


@enforce_types
def parse_json_main_index(out_dir: Path=OUTPUT_DIR) -> Iterator[Link]:
    """parse an archive index json file and return the list of links"""

    index_path = Path(out_dir) / JSON_INDEX_FILENAME
    if index_path.exists():
        with open(index_path, 'r', encoding='utf-8') as f:
            try:
                links = pyjson.load(f)['links']
                if links:
                    Link.from_json(links[0])
            except Exception as err:
                print("    {lightyellow}! Found an index.json in the project root but couldn't load links from it: {} {}".format(
                    err.__class__.__name__,
                    err,
                    **ANSI,
                ))
                return ()

            for link_json in links:
                try:
                    yield Link.from_json(link_json)
                except KeyError:
                    try:
                        detail_index_path = Path(OUTPUT_DIR) / ARCHIVE_DIR_NAME / link_json['timestamp']
                        yield parse_json_link_details(str(detail_index_path))
                    except KeyError: 
                        # as a last effort, try to guess the missing values out of existing ones
                        try:
                            yield Link.from_json(link_json, guess=True)
                        except KeyError:
                            print("    {lightyellow}! Failed to load the index.json from {}".format(detail_index_path, **ANSI))
                            continue
    return ()

### Link Details Index

@enforce_types
def write_json_link_details(link: Link, out_dir: Optional[str]=None) -> None:
    """write a json file with some info about the link"""
    
    out_dir = out_dir or link.link_dir
    path = Path(out_dir) / JSON_INDEX_FILENAME
    atomic_write(str(path), link._asdict(extended=True))


@enforce_types
def parse_json_link_details(out_dir: Union[Path, str], guess: Optional[bool]=False) -> Optional[Link]:
    """load the json link index from a given directory"""
    existing_index = Path(out_dir) / JSON_INDEX_FILENAME
    if existing_index.exists():
        with open(existing_index, 'r', encoding='utf-8') as f:
            try:
                link_json = pyjson.load(f)
                return Link.from_json(link_json, guess)
            except pyjson.JSONDecodeError:
                pass
    return None


@enforce_types
def parse_json_links_details(out_dir: Union[Path, str]) -> Iterator[Link]:
    """read through all the archive data folders and return the parsed links"""

    for entry in os.scandir(Path(out_dir) / ARCHIVE_DIR_NAME):
        if entry.is_dir(follow_symlinks=True):
            if (Path(entry.path) / 'index.json').exists():
                try:
                    link = parse_json_link_details(entry.path)
                except KeyError:
                    link = None
                if link:
                    yield link



### Helpers

class ExtendedEncoder(pyjson.JSONEncoder):
    """
    Extended json serializer that supports serializing several model
    fields and objects
    """

    def default(self, obj):
        cls_name = obj.__class__.__name__

        if hasattr(obj, '_asdict'):
            return obj._asdict()

        elif isinstance(obj, bytes):
            return obj.decode()

        elif isinstance(obj, datetime):
            return obj.isoformat()

        elif isinstance(obj, Exception):
            return '{}: {}'.format(obj.__class__.__name__, obj)

        elif cls_name in ('dict_items', 'dict_keys', 'dict_values'):
            return tuple(obj)

        return pyjson.JSONEncoder.default(self, obj)


@enforce_types
def to_json(obj: Any, indent: Optional[int]=4, sort_keys: bool=True, cls=ExtendedEncoder) -> str:
    return pyjson.dumps(obj, indent=indent, sort_keys=sort_keys, cls=ExtendedEncoder)

