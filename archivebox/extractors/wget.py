__package__ = 'archivebox.extractors'

import os
import re

from typing import Optional
from datetime import datetime

from ..index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from ..system import run, chmod_file
from ..util import (
    enforce_types,
    is_static_file,
    without_scheme,
    without_fragment,
    without_query,
    path,
    domain,
    urldecode,
)
from ..config import (
    TIMEOUT,
    SAVE_WGET,
    SAVE_WARC,
    WGET_BINARY,
    WGET_VERSION,
    RESTRICT_FILE_NAMES,
    CHECK_SSL_VALIDITY,
    SAVE_WGET_REQUISITES,
    WGET_AUTO_COMPRESSION,
    WGET_USER_AGENT,
    COOKIES_FILE,
)
from ..logging_util import TimedProgress


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
        '--timeout={}'.format(timeout),
        *(['--restrict-file-names={}'.format(RESTRICT_FILE_NAMES)] if RESTRICT_FILE_NAMES else []),
        *(['--warc-file={}'.format(warc_path)] if SAVE_WARC else []),
        *(['--page-requisites'] if SAVE_WGET_REQUISITES else []),
        *(['--user-agent={}'.format(WGET_USER_AGENT)] if WGET_USER_AGENT else []),
        *(['--load-cookies', COOKIES_FILE] if COOKIES_FILE else []),
        *(['--compression=auto'] if WGET_AUTO_COMPRESSION else []),
        *([] if SAVE_WARC else ['--timestamping']),
        *([] if CHECK_SSL_VALIDITY else ['--no-check-certificate', '--no-hsts']),
        link.url,
    ]

    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=out_dir, timeout=timeout)
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
        hints = (
            'Got wget response code: {}.'.format(result.returncode),
            *output_tail,
        )

        # Check for common failure cases
        if (result.returncode > 0 and files_downloaded < 1) or output is None:
            if b'403: Forbidden' in result.stderr:
                raise ArchiveError('403 Forbidden (try changing WGET_USER_AGENT)', hints)
            if b'404: Not Found' in result.stderr:
                raise ArchiveError('404 Not Found', hints)
            if b'ERROR 500: Internal Server Error' in result.stderr:
                raise ArchiveError('500 Internal Server Error', hints)
            raise ArchiveError('Wget failed or got an error from the server', hints)
        chmod_file(output, cwd=out_dir)
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


@enforce_types
def wget_output_path(link: Link) -> Optional[str]:
    """calculate the path to the wgetted .html file, since wget may
    adjust some paths to be different than the base_url path.

    See docs on wget --adjust-extension (-E)
    """
    if is_static_file(link.url):
        return without_scheme(without_fragment(link.url))

    # Wget downloads can save in a number of different ways depending on the url:
    #    https://example.com
    #       > example.com/index.html
    #    https://example.com?v=zzVa_tX1OiI
    #       > example.com/index.html?v=zzVa_tX1OiI.html
    #    https://www.example.com/?v=zzVa_tX1OiI
    #       > example.com/index.html?v=zzVa_tX1OiI.html

    #    https://example.com/abc
    #       > example.com/abc.html
    #    https://example.com/abc/
    #       > example.com/abc/index.html
    #    https://example.com/abc?v=zzVa_tX1OiI.html
    #       > example.com/abc?v=zzVa_tX1OiI.html
    #    https://example.com/abc/?v=zzVa_tX1OiI.html
    #       > example.com/abc/index.html?v=zzVa_tX1OiI.html

    #    https://example.com/abc/test.html
    #       > example.com/abc/test.html
    #    https://example.com/abc/test?v=zzVa_tX1OiI
    #       > example.com/abc/test?v=zzVa_tX1OiI.html
    #    https://example.com/abc/test/?v=zzVa_tX1OiI
    #       > example.com/abc/test/index.html?v=zzVa_tX1OiI.html

    # There's also lots of complexity around how the urlencoding and renaming
    # is done for pages with query and hash fragments or extensions like shtml / htm / php / etc

    # Since the wget algorithm for -E (appending .html) is incredibly complex
    # and there's no way to get the computed output path from wget
    # in order to avoid having to reverse-engineer how they calculate it,
    # we just look in the output folder read the filename wget used from the filesystem
    full_path = without_fragment(without_query(path(link.url))).strip('/')
    search_dir = os.path.join(
        link.link_dir,
        domain(link.url).replace(":", "+"),
        urldecode(full_path),
    )
    for _ in range(4):
        if os.path.exists(search_dir):
            if os.path.isdir(search_dir):
                html_files = [
                    f for f in os.listdir(search_dir)
                    if re.search(".+\\.[Ss]?[Hh][Tt][Mm][Ll]?$", f, re.I | re.M)
                ]
                if html_files:
                    path_from_link_dir = search_dir.split(link.link_dir)[-1].strip('/')
                    return os.path.join(path_from_link_dir, html_files[0])

        # Move up one directory level
        search_dir = search_dir.rsplit('/', 1)[0]

        if search_dir == link.link_dir:
            break

    return None
