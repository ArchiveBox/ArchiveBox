__package__ = 'archivebox.extractors'

import os

from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveOutput
from ..system import chmod_file, run
from ..util import enforce_types, domain
from ..config import (
    TIMEOUT,
    SAVE_FAVICON,
    CURL_BINARY,
    CURL_VERSION,
    CHECK_SSL_VALIDITY,
    CURL_USER_AGENT,
)
from ..cli.logging import TimedProgress


@enforce_types
def should_save_favicon(link: Link, out_dir: Optional[str]=None) -> bool:
    out_dir = out_dir or link.link_dir
    if os.path.exists(os.path.join(out_dir, 'favicon.ico')):
        return False

    return SAVE_FAVICON
    
@enforce_types
def save_favicon(link: Link, out_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download site favicon from google's favicon api"""

    out_dir = out_dir or link.link_dir
    output: ArchiveOutput = 'favicon.ico'
    cmd = [
        CURL_BINARY,
        '--silent',
        '--max-time', str(timeout),
        '--location',
        '--output', str(output),
        *(['--user-agent', '{}'.format(CURL_USER_AGENT)] if CURL_USER_AGENT else []),
        *([] if CHECK_SSL_VALIDITY else ['--insecure']),
        'https://www.google.com/s2/favicons?domain={}'.format(domain(link.url)),
    ]
    status = 'pending'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        run(cmd, cwd=out_dir, timeout=timeout)
        chmod_file(output, cwd=out_dir)
        status = 'succeeded'
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
