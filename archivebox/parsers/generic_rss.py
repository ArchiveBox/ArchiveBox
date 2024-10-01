__package__ = 'archivebox.parsers'


from typing import IO, Iterable
from time import mktime
from feedparser import parse as feedparser

from ..index.schema import Link
from archivebox.misc.util import (
    htmldecode,
    enforce_types
)

@enforce_types
def parse_generic_rss_export(rss_file: IO[str], **_kwargs) -> Iterable[Link]:
    """Parse RSS XML-format files into links"""

    rss_file.seek(0)
    feed = feedparser(rss_file.read())
    for item in feed.entries:
        url = item.link
        title = item.title
        time = mktime(item.updated_parsed)

        try:
            tags = ','.join(map(lambda tag: tag.term, item.tags))
        except AttributeError:
            tags = ''

        if url is None:
            # Yielding a Link with no URL will
            # crash on a URL validation assertion
            continue

        yield Link(
            url=htmldecode(url),
            timestamp=str(time),
            title=htmldecode(title) or None,
            tags=tags,
            sources=[rss_file.name],
        )


KEY = 'rss'
NAME = 'Generic RSS'
PARSER = parse_generic_rss_export
