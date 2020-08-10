__package__ = 'archivebox.extractors'

from pathlib import Path

from typing import Optional
import json

from ..index.schema import Link, ArchiveResult, ArchiveError
from ..system import run, chmod_file
from ..util import (
    enforce_types,
    is_static_file,
    chrome_args,
)
from ..config import (
    TIMEOUT,
    SAVE_SINGLEFILE,
    SINGLEFILE_BINARY,
    SINGLEFILE_VERSION,
    CHROME_BINARY,
)
from ..logging_util import TimedProgress


@enforce_types
def should_save_singlefile(link: Link, out_dir: Optional[str]=None) -> bool:
    out_dir = out_dir or link.link_dir
    if is_static_file(link.url):
        return False

    output = Path(out_dir or link.link_dir) / 'singlefile.html'
    return SAVE_SINGLEFILE and (not output.exists())


@enforce_types
def save_singlefile(link: Link, out_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download full site using single-file"""

    out_dir = out_dir or link.link_dir
    output = str(Path(out_dir).absolute() / "singlefile.html")

    browser_args = chrome_args(TIMEOUT=0)

    # SingleFile CLI Docs: https://github.com/gildas-lormeau/SingleFile/tree/master/cli
    cmd = [
        SINGLEFILE_BINARY,
        '--browser-executable-path={}'.format(CHROME_BINARY),
        '--browser-args="{}"'.format(json.dumps(browser_args[1:])),
        link.url,
        output
    ]

    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=out_dir, timeout=timeout)

        # parse out number of files downloaded from last line of stderr:
        #  "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', 3)[-3:]
            if line.strip()
        ]
        hints = (
            'Got single-file response code: {}.'.format(result.returncode),
            *output_tail,
        )

        # Check for common failure cases
        if (result.returncode > 0):
            raise ArchiveError('SingleFile was not able to archive the page', hints)
        chmod_file(output)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=out_dir,
        cmd_version=SINGLEFILE_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
