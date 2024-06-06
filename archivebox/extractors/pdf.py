__package__ = 'archivebox.extractors'

from pathlib import Path
from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from ..system import run, chmod_file
from ..util import (
    enforce_types,
    is_static_file,
    chrome_args,
    chrome_cleanup,
)
from ..config import (
    TIMEOUT,
    SAVE_PDF,
    CHROME_VERSION,
)
from ..logging_util import TimedProgress


def get_output_path():
    return 'output.pdf'


@enforce_types
def should_save_pdf(link: Link, out_dir: Optional[Path]=None, overwrite: Optional[bool]=False) -> bool:
    if is_static_file(link.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / get_output_path()).exists():
        return False

    return SAVE_PDF


@enforce_types
def save_pdf(link: Link, out_dir: Optional[Path]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """print PDF of site to file using chrome --headless"""

    out_dir = out_dir or Path(link.link_dir)
    output: ArchiveOutput = get_output_path()
    cmd = [
        *chrome_args(),
        '--print-to-pdf',
        link.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=str(out_dir), timeout=timeout)

        if result.returncode:
            hints = (result.stderr or result.stdout).decode()
            raise ArchiveError('Failed to save PDF', hints)
        
        chmod_file(get_output_path(), cwd=str(out_dir))
    except Exception as err:
        status = 'failed'
        output = err
        chrome_cleanup()
    finally:
        timer.end()


    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=CHROME_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
