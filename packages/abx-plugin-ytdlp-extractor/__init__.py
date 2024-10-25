__package__ = 'plugins_extractor.ytdlp'
__label__ = 'YT-DLP'
__version__ = '2024.10.14'
__author__ = 'ArchiveBox'
__homepage__ = 'https://github.com/yt-dlp/yt-dlp'

import abx


@abx.hookimpl
def get_PLUGIN():
    return {
        'ytdlp': {
            'PACKAGE': __package__,
            'LABEL': __label__,
            'VERSION': __version__,
            'AUTHOR': __author__,
            'HOMEPAGE': __homepage__,
        }
    }

@abx.hookimpl
def get_CONFIG():
    from .config import YTDLP_CONFIG
    
    return {
        'ytdlp': YTDLP_CONFIG
    }

@abx.hookimpl
def get_BINARIES():
    from .binaries import YTDLP_BINARY, FFMPEG_BINARY
    
    return {
        'ytdlp': YTDLP_BINARY,
        'ffmpeg': FFMPEG_BINARY,
    }

@abx.hookimpl
def ready():
    from .config import YTDLP_CONFIG
    YTDLP_CONFIG.validate()
