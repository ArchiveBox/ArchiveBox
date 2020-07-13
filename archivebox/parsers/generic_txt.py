__package__ = 'archivebox.parsers'
__description__ = 'Plain Text'

import re

from typing import IO, Iterable
from datetime import datetime
from pathlib import Path

from ..index.schema import Link
from ..util import (
    htmldecode,
    enforce_types,
    URL_REGEX
)


@enforce_types
def parse_generic_txt_export(text_file: IO[str]) -> Iterable[Link]:
    """Parse raw links from each line in a text file"""

    text_file.seek(0)
    for line in text_file.readlines():
        if not line.strip():
            continue

        # if the line is a local file path that resolves, then we can archive it
        if Path(line).exists():
            yield Link(
                url=line,
                timestamp=str(datetime.now().timestamp()),
                title=None,
                tags=None,
                sources=[text_file.name],
            )

        # otherwise look for anything that looks like a URL in the line
        for url in re.findall(URL_REGEX, line):
            yield Link(
                url=htmldecode(url),
                timestamp=str(datetime.now().timestamp()),
                title=None,
                tags=None,
                sources=[text_file.name],
            )
