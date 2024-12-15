__package__ = 'abx_plugin_ytdlp'

from pathlib import Path
from typing import Optional

from archivebox.misc.system import run, chmod_file
from archivebox.misc.util import enforce_types, is_static_file, dedupe
from archivebox.index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from archivebox.misc.logging_util import TimedProgress

from .config import YTDLP_CONFIG
from .binaries import YTDLP_BINARY


def get_output_path():
    return 'media/'

def get_embed_path(archiveresult=None):
    if not archiveresult:
        return get_output_path()

    out_dir = archiveresult.snapshot_dir / get_output_path()
    try:
        return get_output_path() + list(out_dir.glob('*.mp4'))[0].name
    except IndexError:
        return get_output_path()


@enforce_types
def should_save_media(link: Link, out_dir: Optional[Path]=None, overwrite: Optional[bool]=False) -> bool:
    
    if is_static_file(link.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / get_output_path()).exists():
        return False

    return YTDLP_CONFIG.USE_YTDLP

@enforce_types
def save_media(link: Link, out_dir: Optional[Path]=None, timeout: int=0) -> ArchiveResult:
    """Download playlists or individual video, audio, and subtitles using youtube-dl or yt-dlp"""

    YTDLP_BIN = YTDLP_BINARY.load()
    assert YTDLP_BIN.abspath and YTDLP_BIN.version

    timeout = timeout or YTDLP_CONFIG.YTDLP_TIMEOUT
    out_dir = out_dir or Path(link.link_dir)
    output: ArchiveOutput = get_output_path()
    output_path = out_dir / output
    output_path.mkdir(exist_ok=True)
    # later options take precedence
    options = [
        *YTDLP_CONFIG.YTDLP_EXTRA_ARGS,
        *([] if YTDLP_CONFIG.YTDLP_CHECK_SSL_VALIDITY else ['--no-check-certificate']),
        # TODO: add --cookies-from-browser={CHROME_USER_DATA_DIR}
    ]
    cmd = [
        str(YTDLP_BIN.abspath),
        *dedupe(options),
        link.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=str(output_path), timeout=timeout + 1, text=True)
        chmod_file(output, cwd=str(out_dir))
        if result.returncode:
            if ('ERROR: Unsupported URL' in result.stderr
                or 'HTTP Error 404' in result.stderr
                or 'HTTP Error 403' in result.stderr
                or 'URL could be a direct video link' in result.stderr
                or 'Unable to extract container ID' in result.stderr):
                # These happen too frequently on non-media pages to warrant printing to console
                pass
            else:
                hints = (
                    'Got yt-dlp response code: {}.'.format(result.returncode),
                    *result.stderr.split('\n'),
                )
                raise ArchiveError('Failed to save media', hints)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    # add video description and subtitles to full-text index
    # Let's try a few different 
    index_texts = [
        # errors:
        # * 'strict' to raise a ValueError exception if there is an
        #   encoding error. The default value of None has the same effect.
        # * 'ignore' ignores errors. Note that ignoring encoding errors
        #   can lead to data loss.
        # * 'xmlcharrefreplace' is only supported when writing to a
        #   file. Characters not supported by the encoding are replaced with
        #   the appropriate XML character reference &#nnn;.
        # There are a few more options described in https://docs.python.org/3/library/functions.html#open
        text_file.read_text(encoding='utf-8', errors='xmlcharrefreplace').strip()
        for text_file in (
            *output_path.glob('*.description'),
            *output_path.glob('*.srt'),
            *output_path.glob('*.vtt'),
            *output_path.glob('*.lrc'),
            *output_path.glob('*.lrc'),
        )
    ]

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=str(YTDLP_BIN.version),
        output=output,
        status=status,
        index_texts=index_texts,
        **timer.stats,
    )
