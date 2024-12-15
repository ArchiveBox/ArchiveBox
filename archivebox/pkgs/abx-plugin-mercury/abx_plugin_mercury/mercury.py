__package__ = 'abx_plugin_mercury'

from pathlib import Path

from subprocess import CompletedProcess
from typing import Optional, List
import json

from archivebox.misc.logging_util import TimedProgress
from archivebox.index.schema import Link, ArchiveResult, ArchiveError
from archivebox.misc.system import run, atomic_write
from archivebox.misc.util import enforce_types, is_static_file
from .config import MERCURY_CONFIG
from .binaries import MERCURY_BINARY



def get_output_path():
    return 'mercury/'

def get_embed_path(archiveresult=None):
    return get_output_path() + 'content.html'


@enforce_types
def ShellError(cmd: List[str], result: CompletedProcess, lines: int=20) -> ArchiveError:
    # parse out last line of stderr
    return ArchiveError(
        f'Got {cmd[0]} response code: {result.returncode}).',
        " ".join(
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', lines)[-lines:]
            if line.strip()
        ),
    )


@enforce_types
def should_save_mercury(link: Link, out_dir: Optional[str]=None, overwrite: Optional[bool]=False) -> bool:
    if is_static_file(link.url):
        return False

    out_dir = Path(out_dir or link.link_dir)

    if not overwrite and (out_dir / get_output_path()).exists():
        return False

    return MERCURY_CONFIG.SAVE_MERCURY


@enforce_types
def save_mercury(link: Link, out_dir: Optional[Path]=None, timeout: int=MERCURY_CONFIG.MERCURY_TIMEOUT) -> ArchiveResult:
    """download reader friendly version using @postlight/mercury-parser"""

    out_dir = Path(out_dir or link.link_dir)
    output_folder = out_dir.absolute() / get_output_path()
    output = get_output_path()
    
    mercury_binary = MERCURY_BINARY.load()
    assert mercury_binary.abspath and mercury_binary.version

    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        output_folder.mkdir(exist_ok=True)
        # later options take precedence
        # By default, get plain text version of article
        cmd = [
            str(mercury_binary.abspath),
            *MERCURY_CONFIG.MERCURY_EXTRA_ARGS,
            '--format=text',
            link.url,
        ]
        result = run(cmd, cwd=out_dir, timeout=timeout)
        try:
            article_text = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise ShellError(cmd, result)
        
        if article_text.get('failed'):
            raise ArchiveError('Mercury was not able to get article text from the URL')

        atomic_write(str(output_folder / "content.txt"), article_text["content"])

        # Get HTML version of article
        cmd = [
            str(mercury_binary.abspath),
            *MERCURY_CONFIG.MERCURY_EXTRA_ARGS,
            link.url
        ]
        result = run(cmd, cwd=out_dir, timeout=timeout)
        try:
            article_json = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise ShellError(cmd, result)

        if article_text.get('failed'):
            raise ArchiveError('Mercury was not able to get article HTML from the URL')

        atomic_write(str(output_folder / "content.html"), article_json.pop("content"))
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
        cmd_version=str(mercury_binary.version),
        output=output,
        status=status,
        **timer.stats,
    )
