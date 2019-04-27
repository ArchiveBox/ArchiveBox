__package__ = 'archivebox.extractors'

from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveOutput
from ..util import (
    enforce_types,
    TimedProgress,
    is_static_file,
    ArchiveError,
    fetch_page_title,
)
from ..config import (
    TIMEOUT,
    SAVE_TITLE,
    CURL_BINARY,
    CURL_VERSION,
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

    output: ArchiveOutput = None
    cmd = [
        CURL_BINARY,
        link.url,
        '|',
        'grep',
        '<title',
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        output = fetch_page_title(link.url, timeout=timeout, progress=False)
        if not output:
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
