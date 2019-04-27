__package__ = 'archivebox.extractors'

import os

from typing import Optional
from datetime import datetime

from ..index.schema import Link, ArchiveResult, ArchiveOutput
from ..util import (
    enforce_types,
    TimedProgress,
    run,
    PIPE,
    wget_output_path,
    ArchiveError,
)
from ..config import (
    TIMEOUT,
    SAVE_WGET,
    SAVE_WARC,
    WGET_BINARY,
    WGET_VERSION,
    CHECK_SSL_VALIDITY,
    SAVE_WGET_REQUISITES,
    WGET_AUTO_COMPRESSION,
    WGET_USER_AGENT,
    COOKIES_FILE,
)



@enforce_types
def should_save_wget(link: Link, out_dir: Optional[str]=None) -> bool:
    output_path = wget_output_path(link)
    out_dir = out_dir or link.link_dir
    if output_path and os.path.exists(os.path.join(out_dir, output_path)):
        return False

    return SAVE_WGET


@enforce_types
def save_wget(link: Link, out_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download full site using wget"""

    out_dir = out_dir or link.link_dir
    if SAVE_WARC:
        warc_dir = os.path.join(out_dir, 'warc')
        os.makedirs(warc_dir, exist_ok=True)
        warc_path = os.path.join('warc', str(int(datetime.now().timestamp())))

    # WGET CLI Docs: https://www.gnu.org/software/wget/manual/wget.html
    output: ArchiveOutput = None
    cmd = [
        WGET_BINARY,
        # '--server-response',  # print headers for better error parsing
        '--no-verbose',
        '--adjust-extension',
        '--convert-links',
        '--force-directories',
        '--backup-converted',
        '--span-hosts',
        '--no-parent',
        '-e', 'robots=off',
        '--restrict-file-names=windows',
        '--timeout={}'.format(timeout),
        *([] if SAVE_WARC else ['--timestamping']),
        *(['--warc-file={}'.format(warc_path)] if SAVE_WARC else []),
        *(['--page-requisites'] if SAVE_WGET_REQUISITES else []),
        *(['--user-agent={}'.format(WGET_USER_AGENT)] if WGET_USER_AGENT else []),
        *(['--load-cookies', COOKIES_FILE] if COOKIES_FILE else []),
        *(['--compression=auto'] if WGET_AUTO_COMPRESSION else []),
        *([] if CHECK_SSL_VALIDITY else ['--no-check-certificate', '--no-hsts']),
        link.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, stdout=PIPE, stderr=PIPE, cwd=out_dir, timeout=timeout)
        output = wget_output_path(link)

        # parse out number of files downloaded from last line of stderr:
        #  "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', 3)[-3:]
            if line.strip()
        ]
        files_downloaded = (
            int(output_tail[-1].strip().split(' ', 2)[1] or 0)
            if 'Downloaded:' in output_tail[-1]
            else 0
        )

        # Check for common failure cases
        if result.returncode > 0 and files_downloaded < 1:
            hints = (
                'Got wget response code: {}.'.format(result.returncode),
                *output_tail,
            )
            if b'403: Forbidden' in result.stderr:
                raise ArchiveError('403 Forbidden (try changing WGET_USER_AGENT)', hints)
            if b'404: Not Found' in result.stderr:
                raise ArchiveError('404 Not Found', hints)
            if b'ERROR 500: Internal Server Error' in result.stderr:
                raise ArchiveError('500 Internal Server Error', hints)
            raise ArchiveError('Got an error from the server', hints)

        # chmod_file(output, cwd=out_dir)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=out_dir,
        cmd_version=WGET_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
