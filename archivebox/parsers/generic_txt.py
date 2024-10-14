__package__ = 'archivebox.parsers'
__description__ = 'Plain Text'

from typing import IO, Iterable
from datetime import datetime, timezone

from ..index.schema import Link
from archivebox.misc.util import (
    htmldecode,
    enforce_types,
    find_all_urls,
)


@enforce_types
def parse_generic_txt_export(text_file: IO[str], **_kwargs) -> Iterable[Link]:
    """Parse links from a text file, ignoring other text"""

    text_file.seek(0)
    for line in text_file.readlines():
        if not line.strip():
            continue

        # # if the line is a local file path that resolves, then we can archive it
        # if line.startswith('file://'):    
        #     try:
        #         if Path(line).exists():
        #             yield Link(
        #                 url=line,
        #                 timestamp=str(datetime.now(timezone.utc).timestamp()),
        #                 title=None,
        #                 tags=None,
        #                 sources=[text_file.name],
        #             )
        #     except (OSError, PermissionError):
        #         # nvm, not a valid path...
        #         pass

        # otherwise look for anything that looks like a URL in the line
        for url in find_all_urls(line):
            yield Link(
                url=htmldecode(url),
                timestamp=str(datetime.now(timezone.utc).timestamp()),
                title=None,
                tags=None,
                sources=[text_file.name],
            )


KEY = 'txt'
NAME = 'Generic TXT'
PARSER = parse_generic_txt_export
