__package__ = 'archivebox.extractors'

import re
from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from ..util import (
    enforce_types,
    is_static_file,
    download_url,
    htmldecode,
)
from ..config import (
    TIMEOUT,
    CHECK_SSL_VALIDITY,
    SAVE_TITLE,
    CURL_BINARY,
    CURL_VERSION,
    CURL_USER_AGENT,
    setup_django,
)
from ..logging_util import TimedProgress


HTML_TITLE_REGEX = re.compile(
    r'<title.*?>'                      # start matching text after <title> tag
    r'(.[^<>]+)',                      # get everything up to these symbols
    re.IGNORECASE | re.MULTILINE | re.DOTALL | re.UNICODE,
)


@enforce_types
def should_save_title(link: Link, out_dir: Optional[str]=None) -> bool:
    # if link already has valid title, skip it
    if link.title and not link.title.lower().startswith('http'):
        return False

    if is_static_file(link.url):
        return False

    return SAVE_TITLE

@enforce_types
def save_title(link: Link, out_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """try to guess the page's title from its content"""

    setup_django(out_dir=out_dir)
    from core.models import Snapshot

    output: ArchiveOutput = None
    cmd = [
        CURL_BINARY,
        '--silent',
        '--max-time', str(timeout),
        '--location',
        '--compressed',
        *(['--user-agent', '{}'.format(CURL_USER_AGENT)] if CURL_USER_AGENT else []),
        *([] if CHECK_SSL_VALIDITY else ['--insecure']),
        link.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        html = download_url(link.url, timeout=timeout)
        match = re.search(HTML_TITLE_REGEX, html)
        output = htmldecode(match.group(1).strip()) if match else None
        if output:
            if not link.title or len(output) >= len(link.title):
                Snapshot.objects.filter(url=link.url, timestamp=link.timestamp).update(title=output)
        else:
            raise ArchiveError('Unable to detect page title')
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=out_dir,
        cmd_version=CURL_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
