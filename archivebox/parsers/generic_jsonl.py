__package__ = 'archivebox.parsers'

import json

from typing import IO, Iterable

from ..index.schema import Link
from archivebox.misc.util import (
    enforce_types,
)

from .generic_json import jsonObjectToLink

def parse_line(line: str):
    if line.strip() != "":
        return json.loads(line)

@enforce_types
def parse_generic_jsonl_export(json_file: IO[str], **_kwargs) -> Iterable[Link]:
    """Parse JSONL format bookmarks export files"""

    json_file.seek(0)

    links = [ parse_line(line) for line in json_file ]

    for link in links:
        if link:
            yield jsonObjectToLink(link,json_file.name)

KEY = 'jsonl'
NAME = 'Generic JSONL'
PARSER = parse_generic_jsonl_export
