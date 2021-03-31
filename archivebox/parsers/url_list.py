__package__ = 'archivebox.parsers'
__description__ = 'URL list'

from typing import IO, Iterable
from datetime import datetime

from ..index.schema import Link
from ..util import (
    enforce_types
)


@enforce_types
def parse_url_list(text_file: IO[str], **_kwargs) -> Iterable[Link]:
    """Parse raw URLs from each line in a text file"""

    text_file.seek(0)
    for line in text_file.readlines():
        url = line.strip()
        if not url:
            continue

        yield Link(
            url=url,
            timestamp=str(datetime.now().timestamp()),
            title=None,
            tags=None,
            sources=[text_file.name],
        )


KEY = 'url_list'
NAME = 'URL List'
PARSER = parse_url_list
