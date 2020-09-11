__package__ = 'archivebox.extractors'

from pathlib import Path
from tempfile import NamedTemporaryFile

from typing import Optional
import json

from ..index.schema import Link, ArchiveResult, ArchiveError
from ..system import run, atomic_write
from ..util import (
    enforce_types,
    get_headers,
    is_static_file,
)
from ..config import (
    TIMEOUT,
    CURL_BINARY,
    CURL_USER_AGENT,
    CURL_VERSION,
    CHECK_SSL_VALIDITY,
    DEPENDENCIES,
)
from ..logging_util import TimedProgress

@enforce_types
def should_save_headers(link: Link, out_dir: Optional[str]=None) -> bool:
    out_dir = out_dir or link.link_dir
    if is_static_file(link.url):
        return False

    output = Path(out_dir or link.link_dir) / 'headers.json'
    return not output.exists()


@enforce_types
def save_headers(link: Link, out_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """Download site headers"""

    out_dir = Path(out_dir or link.link_dir)
    output_folder = out_dir.absolute()
    output: ArchiveOutput = 'headers.json'

    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')

    cmd = [
        CURL_BINARY,
        '-s',
        '-I',
        '-X',
        '-D',
        *(['--user-agent', '{}'.format(CURL_USER_AGENT)] if CURL_USER_AGENT else []),
        *([] if CHECK_SSL_VALIDITY else ['--insecure']),
        link.url,
    ]
    try:
        json_headers = get_headers(link.url)

        output_folder.mkdir(exist_ok=True)
        atomic_write(str(output_folder / "headers.json"), json_headers)

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
