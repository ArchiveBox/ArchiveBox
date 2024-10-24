__package__ = 'archivebox.parsers'

import json

from typing import IO, Iterable
from datetime import datetime, timezone

from ..index.schema import Link
from archivebox.misc.util import (
    htmldecode,
    enforce_types,
)

# This gets used by generic_jsonl, too
def jsonObjectToLink(link: str, source: str):
    json_date = lambda s: datetime.strptime(s, '%Y-%m-%dT%H:%M:%S%z')

    # example line
    # {"href":"http:\/\/www.reddit.com\/r\/example","description":"title here","extended":"","meta":"18a973f09c9cc0608c116967b64e0419","hash":"910293f019c2f4bb1a749fb937ba58e3","time":"2014-06-14T15:51:42Z","shared":"no","toread":"no","tags":"reddit android"}]
    # Parse URL
    url = link.get('href') or link.get('url') or link.get('URL')
    if not url:
        raise Exception('JSON must contain URL in each entry [{"url": "http://...", ...}, ...]')

    # Parse the timestamp
    ts_str = str(datetime.now(timezone.utc).timestamp())
    if link.get('timestamp'):
        # chrome/ff histories use a very precise timestamp
        ts_str = str(link['timestamp'] / 10000000)
    elif link.get('time'):
        ts_str = str(json_date(link['time'].split(',', 1)[0]).timestamp())
    elif link.get('created_at'):
        ts_str = str(json_date(link['created_at']).timestamp())
    elif link.get('created'):
        ts_str = str(json_date(link['created']).timestamp())
    elif link.get('date'):
        ts_str = str(json_date(link['date']).timestamp())
    elif link.get('bookmarked'):
        ts_str = str(json_date(link['bookmarked']).timestamp())
    elif link.get('saved'):
        ts_str = str(json_date(link['saved']).timestamp())

    # Parse the title
    title = None
    if link.get('title'):
        title = link['title'].strip()
    elif link.get('description'):
        title = link['description'].replace(' — Readability', '').strip()
    elif link.get('name'):
        title = link['name'].strip()

    # if we have a list, join it with commas
    tags = link.get('tags')
    if type(tags) == list:
        tags = ','.join(tags)
    elif type(tags) == str:
        # if there's no comma, assume it was space-separated
        if ',' not in tags:
            tags = tags.replace(' ', ',')

    return Link(
        url=htmldecode(url),
        timestamp=ts_str,
        title=htmldecode(title) or None,
        tags=htmldecode(tags),
        sources=[source],
    )

@enforce_types
def parse_generic_json_export(json_file: IO[str], **_kwargs) -> Iterable[Link]:
    """Parse JSON-format bookmarks export files (produced by pinboard.in/export/, or wallabag)"""

    json_file.seek(0)

    links = json.load(json_file)
    if type(links) != list:
        raise Exception('JSON parser expects list of objects, maybe this is JSONL?')
    
    for link in links:
        if link:
            yield jsonObjectToLink(link, json_file.name)

KEY = 'json'
NAME = 'Generic JSON'
PARSER = parse_generic_json_export
