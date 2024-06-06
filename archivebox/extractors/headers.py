__package__ = 'archivebox.extractors'

from pathlib import Path

from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveOutput
from ..system import atomic_write
from ..util import (
    enforce_types,
    get_headers,
    dedupe,
)
from ..config import (
    TIMEOUT,
    CURL_BINARY,
    CURL_ARGS,
    CURL_EXTRA_ARGS,
    CURL_USER_AGENT,
    CURL_VERSION,
    CHECK_SSL_VALIDITY,
    SAVE_HEADERS
)
from ..logging_util import TimedProgress

def get_output_path():
    return 'headers.json'


@enforce_types
def should_save_headers(link: Link, out_dir: Optional[str]=None, overwrite: Optional[bool]=False) -> bool:
    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / get_output_path()).exists():
        return False

    return SAVE_HEADERS


@enforce_types
def save_headers(link: Link, out_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """Download site headers"""

    out_dir = Path(out_dir or link.link_dir)
    output_folder = out_dir.absolute()
    output: ArchiveOutput = get_output_path()

    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    # later options take precedence
    options = [
        *CURL_ARGS,
        *CURL_EXTRA_ARGS,
        '--head',
        '--max-time', str(timeout),
        *(['--user-agent', '{}'.format(CURL_USER_AGENT)] if CURL_USER_AGENT else []),
        *([] if CHECK_SSL_VALIDITY else ['--insecure']),
    ]
    cmd = [
        CURL_BINARY,
        *dedupe(options),
        link.url,
    ]
    try:
        json_headers = get_headers(link.url, timeout=timeout)
        output_folder.mkdir(exist_ok=True)
        atomic_write(str(output_folder / get_output_path()), json_headers)
    except (Exception, OSError) as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=CURL_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
