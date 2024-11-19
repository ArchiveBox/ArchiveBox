__package__ = 'abx_plugin_favicon'

from pathlib import Path

from archivebox.misc.system import chmod_file, run
from archivebox.misc.util import enforce_types, domain, dedupe
from archivebox.misc.logging_util import TimedProgress
from archivebox.index.schema import Link, ArchiveResult, ArchiveOutput

from abx_plugin_curl.config import CURL_CONFIG
from abx_plugin_curl.binaries import CURL_BINARY

from .config import FAVICON_CONFIG


@enforce_types
def should_save_favicon(link: Link, out_dir: str | Path | None=None, overwrite: bool=False) -> bool:
    assert link.link_dir
    out_dir = Path(out_dir or link.link_dir)
    if not overwrite and (out_dir / 'favicon.ico').exists():
        return False

    return FAVICON_CONFIG.SAVE_FAVICON

@enforce_types
def get_output_path():
    return 'favicon.ico'


@enforce_types
def save_favicon(link: Link, out_dir: str | Path | None=None, timeout: int=CURL_CONFIG.CURL_TIMEOUT) -> ArchiveResult:
    """download site favicon from google's favicon api"""

    curl_binary = CURL_BINARY.load()
    assert curl_binary.abspath and curl_binary.version

    out_dir = Path(out_dir or link.link_dir)
    assert out_dir.exists()

    output: ArchiveOutput = 'favicon.ico'
    # later options take precedence
    options = [
        *CURL_CONFIG.CURL_ARGS,
        *CURL_CONFIG.CURL_EXTRA_ARGS,
        '--max-time', str(timeout),
        '--output', str(output),
        *(['--user-agent', '{}'.format(CURL_CONFIG.CURL_USER_AGENT)] if CURL_CONFIG.CURL_USER_AGENT else []),
        *([] if CURL_CONFIG.CURL_CHECK_SSL_VALIDITY else ['--insecure']),
    ]
    cmd = [
        str(curl_binary.abspath),
        *dedupe(options),
        FAVICON_CONFIG.FAVICON_PROVIDER.format(domain(link.url)),
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
        cmd_version=str(curl_binary.version),
        output=output,
        status=status,
        **timer.stats,
    )
