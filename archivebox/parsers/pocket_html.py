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
def parse_pocket_html_export(html_file: IO[str], **_kwargs) -> Iterable[Link]:
    """Parse Pocket-format bookmarks export files (produced by getpocket.com/export/)"""

    html_file.seek(0)
    pattern = re.compile("^\\s*<li><a href=\"(.+)\" time_added=\"(\\d+)\" tags=\"(.*)\">(.+)</a></li>", re.UNICODE)
    for line in html_file:
        if match := pattern.search(line):
            url = match[1].replace('http://www.readability.com/read?url=', '')
            time = datetime.fromtimestamp(float(match[2]))
            tags = match[3]
            title = (
                match[4]
                .replace(' — Readability', '')
                .replace('http://www.readability.com/read?url=', '')
            )

            yield Link(
                url=htmldecode(url),
                timestamp=str(time.timestamp()),
                title=htmldecode(title) or None,
                tags=tags or '',
                sources=[html_file.name],
            )


KEY = 'pocket_html'
NAME = 'Pocket HTML'
PARSER = parse_pocket_html_export
