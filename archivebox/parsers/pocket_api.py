__package__ = 'archivebox.parsers'


import re

from typing import IO, Iterable, Optional
from configparser import ConfigParser

from pocket import Pocket

from archivebox.config import CONSTANTS
from archivebox.misc.util import enforce_types
from archivebox.misc.system import atomic_write
from archivebox.config.legacy import (
    POCKET_CONSUMER_KEY,
    POCKET_ACCESS_TOKENS,
)

from ..index.schema import Link


COUNT_PER_PAGE = 500
API_DB_PATH = CONSTANTS.SOURCES_DIR / 'pocket_api.db'

# search for broken protocols that sometimes come from the Pocket API
_BROKEN_PROTOCOL_RE = re.compile('^(http[s]?)(:/(?!/))')


def get_pocket_articles(api: Pocket, since=None, page=0):
    body, headers = api.get(
        state='archive',
        sort='oldest',
        since=since,
        count=COUNT_PER_PAGE,
        offset=page * COUNT_PER_PAGE,
    )

    articles = body['list'].values() if isinstance(body['list'], dict) else body['list']
    returned_count = len(articles)

    yield from articles

    if returned_count == COUNT_PER_PAGE:
        yield from get_pocket_articles(api, since=since, page=page + 1)
    else:
        api.last_since = body['since']


def link_from_article(article: dict, sources: list):
    url: str = article.get('resolved_url') or article['given_url']
    broken_protocol = _BROKEN_PROTOCOL_RE.match(url)
    if broken_protocol:
        url = url.replace(f'{broken_protocol.group(1)}:/', f'{broken_protocol.group(1)}://')
    title = article.get('resolved_title') or article.get('given_title') or url

    return Link(
        url=url,
        timestamp=article['time_read'],
        title=title,
        tags=article.get('tags'),
        sources=sources
    )


def write_since(username: str, since: str):
    if not API_DB_PATH.exists():
        atomic_write(API_DB_PATH, '')

    since_file = ConfigParser()
    since_file.optionxform = str
    since_file.read(API_DB_PATH)

    since_file[username] = {
        'since': since
    }

    with open(API_DB_PATH, 'w+') as new:
        since_file.write(new)


def read_since(username: str) -> Optional[str]:
    if not API_DB_PATH.exists():
        atomic_write(API_DB_PATH, '')

    config_file = ConfigParser()
    config_file.optionxform = str
    config_file.read(API_DB_PATH)

    return config_file.get(username, 'since', fallback=None)


@enforce_types
def should_parse_as_pocket_api(text: str) -> bool:
    return text.startswith('pocket://')


@enforce_types
def parse_pocket_api_export(input_buffer: IO[str], **_kwargs) -> Iterable[Link]:
    """Parse bookmarks from the Pocket API"""

    input_buffer.seek(0)
    pattern = re.compile(r"^pocket:\/\/(\w+)")
    for line in input_buffer:
        if should_parse_as_pocket_api(line):
            
            username = pattern.search(line).group(1)
            api = Pocket(POCKET_CONSUMER_KEY, POCKET_ACCESS_TOKENS[username])
            api.last_since = None
    
            for article in get_pocket_articles(api, since=read_since(username)):
                yield link_from_article(article, sources=[line])
    
            write_since(username, api.last_since)


KEY = 'pocket_api'
NAME = 'Pocket API'
PARSER = parse_pocket_api_export
