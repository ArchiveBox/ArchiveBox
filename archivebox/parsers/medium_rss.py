__package__ = 'archivebox.parsers'


from typing import IO, Iterable
from datetime import datetime

from xml.etree import ElementTree

from ..index.schema import Link
from archivebox.misc.util import (
    htmldecode,
    enforce_types,
)


@enforce_types
def parse_medium_rss_export(rss_file: IO[str], **_kwargs) -> Iterable[Link]:
    """Parse Medium RSS feed files into links"""

    rss_file.seek(0)
    root = ElementTree.parse(rss_file).getroot()
    items = root.find("channel").findall("item")                        # type: ignore
    for item in items:
        url = item.find("link").text                                    # type: ignore
        title = item.find("title").text.strip()                         # type: ignore
        ts_str = item.find("pubDate").text                              # type: ignore
        time = datetime.strptime(ts_str, "%a, %d %b %Y %H:%M:%S %Z")    # type: ignore
        
        yield Link(
            url=htmldecode(url),
            timestamp=str(time.timestamp()),
            title=htmldecode(title) or None,
            tags=None,
            sources=[rss_file.name],
        )


KEY = 'medium_rss'
NAME = 'Medium RSS'
PARSER = parse_medium_rss_export
