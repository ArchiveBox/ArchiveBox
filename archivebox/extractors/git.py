__package__ = 'archivebox.extractors'


from pathlib import Path
from typing import Optional

from archivebox.misc.system import run, chmod_file
from archivebox.misc.util import (
    enforce_types,
    is_static_file,
    domain,
    extension,
    without_query,
    without_fragment,
)
from archivebox.plugins_extractor.git.apps import GIT_CONFIG, GIT_BINARY
from ..logging_util import TimedProgress
from ..index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError


def get_output_path():
    return 'git/'

def get_embed_path(archiveresult=None):
    if not archiveresult:
        return get_output_path()

    try:
        return get_output_path() + list((archiveresult.snapshot_dir / get_output_path()).glob('*'))[0].name + '/'
    except IndexError:
        pass

    return get_output_path()

@enforce_types
def should_save_git(link: Link, out_dir: Optional[Path]=None, overwrite: Optional[bool]=False) -> bool:
    if is_static_file(link.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / get_output_path()).exists():
        return False

    is_clonable_url = (
        (domain(link.url) in GIT_CONFIG.GIT_DOMAINS)
        or (extension(link.url) == 'git')
    )
    if not is_clonable_url:
        return False

    return GIT_CONFIG.SAVE_GIT


@enforce_types
def save_git(link: Link, out_dir: Optional[Path]=None, timeout: int=GIT_CONFIG.GIT_TIMEOUT) -> ArchiveResult:
    """download full site using git"""
    
    git_binary = GIT_BINARY.load()
    assert git_binary.abspath and git_binary.version

    out_dir = out_dir or Path(link.link_dir)
    output: ArchiveOutput = get_output_path()
    output_path = out_dir / output
    output_path.mkdir(exist_ok=True)
    cmd = [
        str(git_binary.abspath),
        'clone',
        *GIT_CONFIG.GIT_ARGS,
        *([] if GIT_CONFIG.GIT_CHECK_SSL_VALIDITY else ['-c', 'http.sslVerify=false']),
        without_query(without_fragment(link.url)),
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=str(output_path), timeout=timeout + 1)
        if result.returncode == 128:
            # ignore failed re-download when the folder already exists
            pass
        elif result.returncode > 0:
            hints = 'Got git response code: {}.'.format(result.returncode)
            raise ArchiveError('Failed to save git clone', hints)

        chmod_file(output, cwd=str(out_dir))

    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=str(git_binary.version),
        output=output,
        status=status,
        **timer.stats,
    )
