__package__ = 'archivebox.extractors'

from pathlib import Path

from typing import Optional
import json

from ..index.schema import Link, ArchiveResult, ArchiveError
from archivebox.misc.system import run, chmod_file
from archivebox.misc.util import enforce_types, is_static_file, dedupe
from ..logging_util import TimedProgress


def get_output_path():
    return 'singlefile.html'


@enforce_types
def should_save_singlefile(link: Link, out_dir: Optional[Path]=None, overwrite: Optional[bool]=False) -> bool:
    from plugins_extractor.singlefile.apps import SINGLEFILE_CONFIG
    
    if is_static_file(link.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / get_output_path()).exists():
        return False

    return SINGLEFILE_CONFIG.SAVE_SINGLEFILE


@enforce_types
def save_singlefile(link: Link, out_dir: Optional[Path]=None, timeout: int=60) -> ArchiveResult:
    """download full site using single-file"""
    
    from plugins_extractor.chrome.apps import CHROME_CONFIG, CHROME_BINARY
    from plugins_extractor.singlefile.apps import SINGLEFILE_CONFIG, SINGLEFILE_BINARY

    CHROME_BIN = CHROME_BINARY.load()
    assert CHROME_BIN.abspath and CHROME_BIN.version
    SINGLEFILE_BIN = SINGLEFILE_BINARY.load()
    assert SINGLEFILE_BIN.abspath and SINGLEFILE_BIN.version

    out_dir = out_dir or Path(link.link_dir)
    output = get_output_path()

    browser_args = CHROME_CONFIG.chrome_args(CHROME_TIMEOUT=0)

    # SingleFile CLI Docs: https://github.com/gildas-lormeau/SingleFile/tree/master/cli
    options = [
        '--browser-executable-path={}'.format(CHROME_BIN.abspath),
        *(["--browser-cookies-file={}".format(SINGLEFILE_CONFIG.SINGLEFILE_COOKIES_FILE)] if SINGLEFILE_CONFIG.SINGLEFILE_COOKIES_FILE else []),
        '--browser-args={}'.format(json.dumps(browser_args)),
        *SINGLEFILE_CONFIG.SINGLEFILE_EXTRA_ARGS,
    ]
    cmd = [
        str(SINGLEFILE_BIN.abspath),
        *dedupe(options),
        link.url,
        output,
    ]

    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    result = None
    try:
        result = run(cmd, cwd=str(out_dir), timeout=timeout, text=True, capture_output=True)

        # parse out number of files downloaded from last line of stderr:
        #  "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).rsplit('\n', 5)[-5:]
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
        cmd[2] = cmd[2].replace('"', "\\\"")
        if result:
            err.hints = (result.stdout + result.stderr).split('\n')
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=str(SINGLEFILE_BIN.version),
        output=output,
        status=status,
        **timer.stats,
    )
