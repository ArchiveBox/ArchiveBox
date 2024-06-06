__package__ = 'archivebox.extractors'

from pathlib import Path
from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from ..system import run, chmod_file, atomic_write
from ..util import (
    enforce_types,
    is_static_file,
    chrome_args,
    chrome_cleanup,
)
from ..config import (
    TIMEOUT,
    SAVE_DOM,
    CHROME_VERSION,
)
from ..logging_util import TimedProgress


def get_output_path():
    return 'output.html'


@enforce_types
def should_save_dom(link: Link, out_dir: Optional[Path]=None, overwrite: Optional[bool]=False) -> bool:
    if is_static_file(link.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / get_output_path()).exists():
        if (out_dir / get_output_path()).stat().st_size > 1:
            return False

    return SAVE_DOM

@enforce_types
def save_dom(link: Link, out_dir: Optional[Path]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """print HTML of site to file using chrome --dump-html"""

    out_dir = out_dir or Path(link.link_dir)
    output: ArchiveOutput = get_output_path()
    output_path = out_dir / output
    cmd = [
        *chrome_args(),
        '--dump-dom',
        link.url
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=str(out_dir), timeout=timeout)
        atomic_write(output_path, result.stdout)

        if result.returncode:
            hints = result.stderr.decode()
            raise ArchiveError('Failed to save DOM', hints)

        chmod_file(output, cwd=str(out_dir))
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
