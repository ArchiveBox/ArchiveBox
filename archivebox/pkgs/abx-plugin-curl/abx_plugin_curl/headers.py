__package__ = 'abx_plugin_curl'

from pathlib import Path

from typing import Optional

from archivebox.index.schema import Link, ArchiveResult, ArchiveOutput
from archivebox.misc.system import atomic_write
from archivebox.misc.util import enforce_types, get_headers, dedupe
from archivebox.misc.logging_util import TimedProgress

from .binaries import CURL_BINARY
from .config import CURL_CONFIG


def get_output_path():
    return 'headers.json'


@enforce_types
def should_save_headers(link: Link, out_dir: Optional[str]=None, overwrite: Optional[bool]=False) -> bool:
    out_dir_path = Path(out_dir or link.link_dir)
    assert out_dir_path
    if not overwrite and (out_dir_path / get_output_path()).exists():
        return False

    return CURL_CONFIG.SAVE_HEADERS


@enforce_types
def save_headers(link: Link, out_dir: Optional[str]=None, timeout: int=CURL_CONFIG.CURL_TIMEOUT) -> ArchiveResult:
    """Download site headers"""

    curl_binary = CURL_BINARY.load()
    assert curl_binary.abspath and curl_binary.version

    out_dir_path = Path(out_dir or link.link_dir)
    output_folder = out_dir_path.absolute()
    output: ArchiveOutput = get_output_path()

    status = 'succeeded'
    timer = TimedProgress(timeout + 1, prefix='      ')
    # later options take precedence
    options = [
        *CURL_CONFIG.CURL_ARGS,
        *CURL_CONFIG.CURL_EXTRA_ARGS,
        '--head',
        '--max-time', str(timeout),
        *(['--user-agent', '{}'.format(CURL_CONFIG.CURL_USER_AGENT)] if CURL_CONFIG.CURL_USER_AGENT else []),
        *([] if CURL_CONFIG.CURL_CHECK_SSL_VALIDITY else ['--insecure']),
    ]
    cmd = [
        str(curl_binary.abspath),
        *dedupe(options),
        link.url,
    ]
    try:
        json_headers = get_headers(link.url, timeout=timeout)
        output_folder.mkdir(exist_ok=True)
        atomic_write(str(output_folder / get_output_path()), json_headers)
    except (Exception, OSError) as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir_path),
        cmd_version=str(curl_binary.version),
        output=output,
        status=status,
        **timer.stats,
    )
