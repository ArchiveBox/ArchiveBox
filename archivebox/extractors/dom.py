__package__ = 'archivebox.extractors'

import os

from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from ..system import run, chmod_file, atomic_write
from ..util import (
    enforce_types,
    is_static_file,
    chrome_args,
)
from ..config import (
    TIMEOUT,
    SAVE_DOM,
    CHROME_VERSION,
)
from ..logging_util import TimedProgress



@enforce_types
def should_save_dom(link: Link, out_dir: Optional[str]=None) -> bool:
    out_dir = out_dir or link.link_dir
    if is_static_file(link.url):
        return False
    
    if os.path.exists(os.path.join(out_dir, 'output.html')):
        return False

    return SAVE_DOM
    
@enforce_types
def save_dom(link: Link, out_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """print HTML of site to file using chrome --dump-html"""

    out_dir = out_dir or link.link_dir
    output: ArchiveOutput = 'output.html'
    output_path = os.path.join(out_dir, str(output))
    cmd = [
        *chrome_args(TIMEOUT=timeout),
        '--dump-dom',
        link.url
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=out_dir, timeout=timeout)
        atomic_write(output_path, result.stdout)

        if result.returncode:
            hints = result.stderr.decode()
            raise ArchiveError('Failed to save DOM', hints)

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
