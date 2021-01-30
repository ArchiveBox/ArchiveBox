__package__ = 'archivebox.extractors'

from pathlib import Path

from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveOutput
from ..system import chmod_file, run
from ..util import enforce_types, domain
from ..config import (
    TIMEOUT,
    SAVE_FAVICON,
    CURL_BINARY,
    CURL_ARGS,
    CURL_VERSION,
    CHECK_SSL_VALIDITY,
    CURL_USER_AGENT,
)
from ..logging_util import TimedProgress


@enforce_types
def should_save_favicon(link: Link, out_dir: Optional[str]=None, overwrite: Optional[bool]=False) -> bool:
    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / 'favicon.ico').exists():
        return False

    return SAVE_FAVICON

@enforce_types
def save_favicon(link: Link, out_dir: Optional[Path]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download site favicon from google's favicon api"""

    out_dir = out_dir or link.link_dir
    output: ArchiveOutput = 'favicon.ico'
    cmd = [
        CURL_BINARY,
        *CURL_ARGS,
        '--max-time', str(timeout),
        '--output', str(output),
        *(['--user-agent', '{}'.format(CURL_USER_AGENT)] if CURL_USER_AGENT else []),
        *([] if CHECK_SSL_VALIDITY else ['--insecure']),
        'https://www.google.com/s2/favicons?domain={}'.format(domain(link.url)),
    ]
    status = 'failed'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        run(cmd, cwd=str(out_dir), timeout=timeout)
        chmod_file(output, cwd=str(out_dir))
        status = 'succeeded'
    except Exception as err:
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
