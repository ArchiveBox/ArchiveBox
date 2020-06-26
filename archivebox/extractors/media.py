__package__ = 'archivebox.extractors'

import os

from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from ..system import run, chmod_file
from ..util import (
    enforce_types,
    is_static_file,
)
from ..config import (
    MEDIA_TIMEOUT,
    SAVE_MEDIA,
    SAVE_PLAYLISTS,
    YOUTUBEDL_BINARY,
    YOUTUBEDL_VERSION,
    CHECK_SSL_VALIDITY
)
from ..cli.logging import TimedProgress


@enforce_types
def should_save_media(link: Link, out_dir: Optional[str]=None) -> bool:
    out_dir = out_dir or link.link_dir

    if is_static_file(link.url):
        return False

    if os.path.exists(os.path.join(out_dir, 'media')):
        return False

    return SAVE_MEDIA

@enforce_types
def save_media(link: Link, out_dir: Optional[str]=None, timeout: int=MEDIA_TIMEOUT) -> ArchiveResult:
    """Download playlists or individual video, audio, and subtitles using youtube-dl"""

    out_dir = out_dir or link.link_dir
    output: ArchiveOutput = 'media'
    output_path = os.path.join(out_dir, str(output))
    os.makedirs(output_path, exist_ok=True)
    cmd = [
        YOUTUBEDL_BINARY,
        '--write-description',
        '--write-info-json',
        '--write-annotations',
        '--write-thumbnail',
        '--no-call-home',
        '--no-check-certificate',
        '--user-agent',
        '--all-subs',
        '--extract-audio',
        '--keep-video',
        '--ignore-errors',
        '--geo-bypass',
        '--audio-format', 'mp3',
        '--audio-quality', '320K',
        '--embed-thumbnail',
        '--add-metadata',
        *(['--yes-playlist'] if SAVE_PLAYLISTS else []),
        *([] if CHECK_SSL_VALIDITY else ['--no-check-certificate']),
        link.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=output_path, timeout=timeout + 1)
        chmod_file(output, cwd=out_dir)
        if result.returncode:
            if (b'ERROR: Unsupported URL' in result.stderr
                or b'HTTP Error 404' in result.stderr
                or b'HTTP Error 403' in result.stderr
                or b'URL could be a direct video link' in result.stderr
                or b'Unable to extract container ID' in result.stderr):
                # These happen too frequently on non-media pages to warrant printing to console
                pass
            else:
                hints = (
                    'Got youtube-dl response code: {}.'.format(result.returncode),
                    *result.stderr.decode().split('\n'),
                )
                raise ArchiveError('Failed to save media', hints)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=out_dir,
        cmd_version=YOUTUBEDL_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
