__package__ = "archivebox.parsers"


import re
import requests
from datetime import datetime

from typing import IO, Iterable, Optional
from configparser import ConfigParser

from archivebox.config import CONSTANTS
from archivebox.misc.util import enforce_types
from archivebox.misc.system import atomic_write
from archivebox.config.legacy import READWISE_READER_TOKENS

from ..index.schema import Link

API_DB_PATH = CONSTANTS.SOURCES_DIR / "readwise_reader_api.db"


class ReadwiseReaderAPI:
    cursor: Optional[str]

    def __init__(self, api_token, cursor=None) -> None:
        self.api_token = api_token
        self.cursor = cursor

    def get_archive(self):
        response = requests.get(
            url="https://readwise.io/api/v3/list/",
            headers={"Authorization": f"Token {self.api_token}"},
            params={
                "location": "archive",
                "pageCursor": self.cursor,
            }
        )
        response.raise_for_status()
        return response

def get_readwise_reader_articles(api: ReadwiseReaderAPI):
    response = api.get_archive()
    body = response.json()
    articles = body["results"]

    yield from articles


    if body['nextPageCursor']:
        api.cursor = body["nextPageCursor"]
        yield from get_readwise_reader_articles(api)


def link_from_article(article: dict, sources: list):
    url: str = article['source_url']
    title = article["title"] or url
    timestamp = datetime.fromisoformat(article['updated_at']).timestamp()

    return Link(
        url=url,
        timestamp=str(timestamp),
        title=title,
        tags="",
        sources=sources,
    )


def write_cursor(username: str, since: str):
    if not API_DB_PATH.exists():
        atomic_write(API_DB_PATH, "")

    since_file = ConfigParser()
    since_file.optionxform = str
    since_file.read(API_DB_PATH)

    since_file[username] = {"since": since}

    with open(API_DB_PATH, "w+") as new:
        since_file.write(new)


def read_cursor(username: str) -> Optional[str]:
    if not API_DB_PATH.exists():
        atomic_write(API_DB_PATH, "")

    config_file = ConfigParser()
    config_file.optionxform = str
    config_file.read(API_DB_PATH)

    return config_file.get(username, "since", fallback=None)




@enforce_types
def should_parse_as_readwise_reader_api(text: str) -> bool:
    return text.startswith("readwise-reader://")


@enforce_types
def parse_readwise_reader_api_export(input_buffer: IO[str], **_kwargs) -> Iterable[Link]:
    """Parse bookmarks from the Readwise Reader API"""

    input_buffer.seek(0)
    pattern = re.compile(r"^readwise-reader:\/\/(\w+)")
    for line in input_buffer:
        if should_parse_as_readwise_reader_api(line):
            username = pattern.search(line).group(1)
            api = ReadwiseReaderAPI(READWISE_READER_TOKENS[username], cursor=read_cursor(username))

            for article in get_readwise_reader_articles(api):
                yield link_from_article(article, sources=[line])

            if api.cursor:
                write_cursor(username, api.cursor)


KEY = "readwise_reader_api"
NAME = "Readwise Reader API"
PARSER = parse_readwise_reader_api_export
