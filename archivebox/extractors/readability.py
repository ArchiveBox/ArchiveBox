__package__ = 'archivebox.extractors'

from pathlib import Path

from typing import Optional
import json

from ..index.schema import Link, ArchiveResult, ArchiveError
from ..system import run, atomic_write
from ..util import (
    enforce_types,
    download_url,
    
)
from ..config import (
    TIMEOUT,
    SAVE_READABILITY,
    READABILITY_BINARY,
    READABILITY_VERSION,
    CHROME_BINARY,
)
from ..logging_util import TimedProgress


@enforce_types
def should_save_readability(link: Link, out_dir: Optional[str]=None) -> bool:
    out_dir = out_dir or link.link_dir

    output = Path(out_dir or link.link_dir) / 'readability.json'
    return SAVE_READABILITY and (not output.exists())


@enforce_types
def save_readability(link: Link, out_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download reader friendly version using @mozilla/readability"""

    out_dir = out_dir or link.link_dir
    output = str(Path(out_dir).absolute() / "readability.json")

    document = download_url(link.url)

    # SingleFile CLI Docs: https://github.com/gildas-lormeau/SingleFile/tree/master/cli
    cmd = [
        READABILITY_BINARY,
        document
    ]

    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=out_dir, timeout=timeout)
        result_json = json.loads(result.stdout)
        atomic_write(output, result_json)

        # parse out number of files downloaded from last line of stderr:
        #  "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', 3)[-3:]
            if line.strip()
        ]
        hints = (
            'Got readability response code: {}.'.format(result.returncode),
            *output_tail,
        )

        # Check for common failure cases
        if (result.returncode > 0):
            raise ArchiveError('Readability was not able to archive the page', hints)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=out_dir,
        cmd_version=READABILITY_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
