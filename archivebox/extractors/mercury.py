__package__ = 'archivebox.extractors'

from pathlib import Path

from subprocess import CompletedProcess
from typing import Optional, List
import json

from ..index.schema import Link, ArchiveResult, ArchiveError
from ..system import run, atomic_write
from ..util import (
    enforce_types,
    is_static_file,

)
from ..config import (
    TIMEOUT,
    SAVE_MERCURY,
    DEPENDENCIES,
    MERCURY_VERSION,
)
from ..logging_util import TimedProgress



@enforce_types
def ShellError(cmd: List[str], result: CompletedProcess, lines: int=20) -> ArchiveError:
    # parse out last line of stderr
    return ArchiveError(
        f'Got {cmd[0]} response code: {result.returncode}).',
        *(
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', lines)[-lines:]
            if line.strip()
        ),
    )


@enforce_types
def should_save_mercury(link: Link, out_dir: Optional[str]=None) -> bool:
    out_dir = out_dir or link.link_dir
    if is_static_file(link.url):
        return False

    output = Path(out_dir or link.link_dir) / 'mercury'
    return SAVE_MERCURY and MERCURY_VERSION and (not output.exists())


@enforce_types
def save_mercury(link: Link, out_dir: Optional[Path]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download reader friendly version using @postlight/mercury-parser"""

    out_dir = Path(out_dir or link.link_dir)
    output_folder = out_dir.absolute() / "mercury"
    output = str(output_folder)

    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        # Get plain text version of article
        cmd = [
            DEPENDENCIES['MERCURY_BINARY']['path'],
            link.url,
            "--format=text"
        ]
        result = run(cmd, cwd=out_dir, timeout=timeout)
        try:
            article_text = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise ShellError(cmd, result)
        
        # Get HTML version of article
        cmd = [
            DEPENDENCIES['MERCURY_BINARY']['path'],
            link.url
        ]
        result = run(cmd, cwd=out_dir, timeout=timeout)
        try:
            article_json = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise ShellError(cmd, result)

        output_folder.mkdir(exist_ok=True)
        atomic_write(str(output_folder / "content.html"), article_json.pop("content"))
        atomic_write(str(output_folder / "content.txt"), article_text["content"])
        atomic_write(str(output_folder / "article.json"), article_json)

        # Check for common failure cases
        if (result.returncode > 0):
            raise ShellError(cmd, result)
    except (ArchiveError, Exception, OSError) as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=MERCURY_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
