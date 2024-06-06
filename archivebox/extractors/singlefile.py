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
    dedupe,
)
from ..config import (
    TIMEOUT,
    SAVE_SINGLEFILE,
    DEPENDENCIES,
    SINGLEFILE_VERSION,
    SINGLEFILE_ARGS,
    SINGLEFILE_EXTRA_ARGS,
    CHROME_BINARY,
    COOKIES_FILE,
)
from ..logging_util import TimedProgress


def get_output_path():
    return 'singlefile.html'


@enforce_types
def should_save_singlefile(link: Link, out_dir: Optional[Path]=None, overwrite: Optional[bool]=False) -> bool:
    if is_static_file(link.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / get_output_path()).exists():
        return False

    return SAVE_SINGLEFILE


@enforce_types
def save_singlefile(link: Link, out_dir: Optional[Path]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download full site using single-file"""

    out_dir = out_dir or Path(link.link_dir)
    output = get_output_path()

    browser_args = chrome_args(CHROME_TIMEOUT=0)

    # SingleFile CLI Docs: https://github.com/gildas-lormeau/SingleFile/tree/master/cli
    browser_args = '--browser-args={}'.format(json.dumps(browser_args[1:]))
    # later options take precedence
    options = [
        '--browser-executable-path={}'.format(CHROME_BINARY),
        *(["--browser-cookies-file={}".format(COOKIES_FILE)] if COOKIES_FILE else []),
        browser_args,
        *SINGLEFILE_ARGS,
        *SINGLEFILE_EXTRA_ARGS,
    ]
    cmd = [
        DEPENDENCIES['SINGLEFILE_BINARY']['path'],
        *dedupe(options),
        link.url,
        output,
    ]

    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    result = None
    try:
        result = run(cmd, cwd=str(out_dir), timeout=timeout)

        # parse out number of files downloaded from last line of stderr:
        #  "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', 5)[-5:]
            if line.strip()
        ]
        hints = (
            'Got single-file response code: {}.'.format(result.returncode),
            *output_tail,
        )

        # Check for common failure cases
        if (result.returncode > 0) or not (out_dir / output).is_file():
            raise ArchiveError(f'SingleFile was not able to archive the page (status={result.returncode})', hints)
        chmod_file(output, cwd=str(out_dir))
    except (Exception, OSError) as err:
        status = 'failed'
        # TODO: Make this prettier. This is necessary to run the command (escape JSON internal quotes).
        cmd[2] = browser_args.replace('"', "\\\"")
        if result:
            err.hints = (result.stdout + result.stderr).decode().split('\n')
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=SINGLEFILE_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
