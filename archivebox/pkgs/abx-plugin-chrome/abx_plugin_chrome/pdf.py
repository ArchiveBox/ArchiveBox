__package__ = 'abx_plugin_chrome'

from pathlib import Path
from typing import Optional

from archivebox.misc.system import run, chmod_file
from archivebox.misc.util import enforce_types, is_static_file
from archivebox.index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from archivebox.misc.logging_util import TimedProgress

from .config import CHROME_CONFIG
from .binaries import CHROME_BINARY


def get_output_path():
    return 'output.pdf'


@enforce_types
def should_save_pdf(link: Link, out_dir: Optional[Path]=None, overwrite: Optional[bool]=False) -> bool:
    
    if is_static_file(link.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / get_output_path()).exists():
        return False

    return CHROME_CONFIG.SAVE_PDF


@enforce_types
def save_pdf(link: Link, out_dir: Optional[Path]=None, timeout: int=60) -> ArchiveResult:
    """print PDF of site to file using chrome --headless"""

    CHROME_BIN = CHROME_BINARY.load()
    assert CHROME_BIN.abspath and CHROME_BIN.version

    out_dir = out_dir or Path(link.link_dir)
    output: ArchiveOutput = get_output_path()
    cmd = [
        str(CHROME_BIN.abspath),
        *CHROME_CONFIG.chrome_args(),
        '--print-to-pdf',
        link.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=str(out_dir), timeout=timeout, text=True)

        if result.returncode:
            hints = (result.stderr or result.stdout)
            raise ArchiveError('Failed to save PDF', hints)
        
        chmod_file(get_output_path(), cwd=str(out_dir))
    except Exception as err:
        status = 'failed'
        output = err
        CHROME_BINARY.chrome_cleanup_lockfile()
    finally:
        timer.end()


    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=str(CHROME_BINARY.version),
        output=output,
        status=status,
        **timer.stats,
    )
