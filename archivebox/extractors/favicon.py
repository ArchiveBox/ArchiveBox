__package__ = 'archivebox.extractors'

from pathlib import Path

from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveOutput
from archivebox.misc.system import chmod_file, run
from ..util import (
    enforce_types,
    domain,
    dedupe,
)
from ..config.legacy import CONFIG
from ..logging_util import TimedProgress


@enforce_types
def should_save_favicon(link: Link, out_dir: str | Path | None=None, overwrite: bool=False) -> bool:
    assert link.link_dir
    out_dir = Path(out_dir or link.link_dir)
    if not overwrite and (out_dir / 'favicon.ico').exists():
        return False

    return CONFIG.SAVE_FAVICON

@enforce_types
def get_output_path():
    return 'favicon.ico'


@enforce_types
def save_favicon(link: Link, out_dir: str | Path | None=None, timeout: int=CONFIG.TIMEOUT) -> ArchiveResult:
    """download site favicon from google's favicon api"""

    out_dir = Path(out_dir or link.link_dir)
    assert out_dir.exists()

    output: ArchiveOutput = 'favicon.ico'
    # later options take precedence
    options = [
        *CONFIG.CURL_ARGS,
        *CONFIG.CURL_EXTRA_ARGS,
        '--max-time', str(timeout),
        '--output', str(output),
        *(['--user-agent', '{}'.format(CONFIG.CURL_USER_AGENT)] if CONFIG.CURL_USER_AGENT else []),
        *([] if CONFIG.CHECK_SSL_VALIDITY else ['--insecure']),
    ]
    cmd = [
        CONFIG.CURL_BINARY,
        *dedupe(options),
        CONFIG.FAVICON_PROVIDER.format(domain(link.url)),
    ]
    status = 'failed'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        run(cmd, cwd=str(out_dir), timeout=timeout)
        chmod_file(output, cwd=str(out_dir))
        status = 'succeeded'
    except Exception as err:
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=CONFIG.CURL_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
