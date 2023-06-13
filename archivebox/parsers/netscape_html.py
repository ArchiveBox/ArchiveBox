__package__ = 'archivebox.parsers'


import re

from typing import IO, Iterable
from datetime import datetime

from ..index.schema import Link
from ..util import (
    htmldecode,
    enforce_types,
)


@enforce_types
def parse_netscape_html_export(html_file: IO[str], **_kwargs) -> Iterable[Link]:
    """Parse netscape-format bookmarks export files (produced by all browsers)"""

    html_file.seek(0)
    pattern = re.compile("<a href=\"(.+?)\" add_date=\"(\\d+)\"[^>]*>(.+)</a>", re.UNICODE | re.IGNORECASE)
    for line in html_file:
        if match := pattern.search(line):
            url = match[1]
            time = datetime.fromtimestamp(float(match[2]))
            title = match[3].strip()

            yield Link(
                url=htmldecode(url),
                timestamp=str(time.timestamp()),
                title=htmldecode(title) or None,
                tags=None,
                sources=[html_file.name],
            )


KEY = 'netscape_html'
NAME = 'Netscape HTML'
PARSER = parse_netscape_html_export
