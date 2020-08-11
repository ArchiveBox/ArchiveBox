__package__ = 'archivebox.extractors'

import os

from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from ..system import run, chmod_file
from ..util import (
    enforce_types,
    is_static_file,
    domain,
    extension,
    without_query,
    without_fragment,
)
from ..config import (
    TIMEOUT,
    SAVE_GIT,
    GIT_BINARY,
    GIT_VERSION,
    GIT_DOMAINS,
    CHECK_SSL_VALIDITY
)
from ..logging_util import TimedProgress



@enforce_types
def should_save_git(link: Link, out_dir: Optional[str]=None) -> bool:
    out_dir = out_dir or link.link_dir
    if is_static_file(link.url):
        return False

    if os.path.exists(os.path.join(out_dir, 'git')):
        return False

    is_clonable_url = (
        (domain(link.url) in GIT_DOMAINS)
        or (extension(link.url) == 'git')
    )
    if not is_clonable_url:
        return False

    return SAVE_GIT


@enforce_types
def save_git(link: Link, out_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download full site using git"""

    out_dir = out_dir or link.link_dir
    output: ArchiveOutput = 'git'
    output_path = os.path.join(out_dir, str(output))
    os.makedirs(output_path, exist_ok=True)
    cmd = [
        GIT_BINARY,
        'clone',
        '--recursive',
        *([] if CHECK_SSL_VALIDITY else ['-c', 'http.sslVerify=false']),
        without_query(without_fragment(link.url)),
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=output_path, timeout=timeout + 1)
        if result.returncode == 128:
            # ignore failed re-download when the folder already exists
            pass
        elif result.returncode > 0:
            hints = 'Got git response code: {}.'.format(result.returncode)
            raise ArchiveError('Failed to save git clone', hints)

        chmod_file(output, cwd=out_dir)

    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=out_dir,
        cmd_version=GIT_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
