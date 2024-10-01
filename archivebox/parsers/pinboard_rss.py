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
def parse_pinboard_rss_export(rss_file: IO[str], **_kwargs) -> Iterable[Link]:
    """Parse Pinboard RSS feed files into links"""

    rss_file.seek(0)
    feed = feedparser(rss_file.read())
    for item in feed.entries:
        url = item.link
        # title will start with "[priv] " if pin was marked private. useful?
        title = item.title
        time = mktime(item.updated_parsed)

        # all tags are in one entry.tags with spaces in it. annoying!
        try:
            tags = item.tags[0].term.replace(' ', ',')
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
            tags=htmldecode(tags) or None,
            sources=[rss_file.name],
        )


KEY = 'pinboard_rss'
NAME = 'Pinboard RSS'
PARSER = parse_pinboard_rss_export
