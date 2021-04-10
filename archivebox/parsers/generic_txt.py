__package__ = 'archivebox.parsers'
__description__ = 'Plain Text'

import re

from typing import IO, Iterable
from datetime import datetime, timezone
from pathlib import Path

from ..index.schema import Link
from ..util import (
    htmldecode,
    enforce_types,
    URL_REGEX
)


@enforce_types
def parse_generic_txt_export(text_file: IO[str], **_kwargs) -> Iterable[Link]:
    """Parse links from a text file, ignoring other text"""

    text_file.seek(0)
    for line in text_file.readlines():
        if not line.strip():
            continue

        # if the line is a local file path that resolves, then we can archive it
        try:
            if Path(line).exists():
                yield Link(
                    url=line,
                    timestamp=str(datetime.now(timezone.utc).timestamp()),
                    title=None,
                    tags=None,
                    sources=[text_file.name],
                )
        except (OSError, PermissionError):
            # nvm, not a valid path...
            pass

        # otherwise look for anything that looks like a URL in the line
        for url in re.findall(URL_REGEX, line):
            yield Link(
                url=htmldecode(url),
                timestamp=str(datetime.now(timezone.utc).timestamp()),
                title=None,
                tags=None,
                sources=[text_file.name],
            )

            # look inside the URL for any sub-urls, e.g. for archive.org links
            # https://web.archive.org/web/20200531203453/https://www.reddit.com/r/socialism/comments/gu24ke/nypd_officers_claim_they_are_protecting_the_rule/fsfq0sw/
            # -> https://www.reddit.com/r/socialism/comments/gu24ke/nypd_officers_claim_they_are_protecting_the_rule/fsfq0sw/
            for sub_url in re.findall(URL_REGEX, line[1:]):
                yield Link(
                    url=htmldecode(sub_url),
                    timestamp=str(datetime.now(timezone.utc).timestamp()),
                    title=None,
                    tags=None,
                    sources=[text_file.name],
                )

KEY = 'txt'
NAME = 'Generic TXT'
PARSER = parse_generic_txt_export
