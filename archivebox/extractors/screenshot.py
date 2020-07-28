__package__ = 'archivebox.extractors'

import os

from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from ..system import run, chmod_file
from ..util import (
    enforce_types,
    is_static_file,
    chrome_args,
)
from ..config import (
    TIMEOUT,
    SAVE_SCREENSHOT,
    CHROME_VERSION,
)
from ..logging_util import TimedProgress



@enforce_types
def should_save_screenshot(link: Link, out_dir: Optional[str]=None) -> bool:
    out_dir = out_dir or link.link_dir
    if is_static_file(link.url):
        return False
    
    if os.path.exists(os.path.join(out_dir, 'screenshot.png')):
        return False

    return SAVE_SCREENSHOT

@enforce_types
def save_screenshot(link: Link, out_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """take screenshot of site using chrome --headless"""
    
    out_dir = out_dir or link.link_dir
    output: ArchiveOutput = 'screenshot.png'
    cmd = [
        *chrome_args(TIMEOUT=timeout),
        '--screenshot',
        link.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=out_dir, timeout=timeout)

        if result.returncode:
            hints = (result.stderr or result.stdout).decode()
            raise ArchiveError('Failed to save screenshot', hints)

        chmod_file(output, cwd=out_dir)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=out_dir,
        cmd_version=CHROME_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
