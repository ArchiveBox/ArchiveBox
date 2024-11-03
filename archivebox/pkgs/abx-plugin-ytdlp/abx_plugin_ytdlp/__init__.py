__package__ = 'abx_plugin_ytdlp'
__label__ = 'YT-DLP'
__homepage__ = 'https://github.com/yt-dlp/yt-dlp'

import abx

@abx.hookimpl
def get_CONFIG():
    from .config import YTDLP_CONFIG
    
    return {
        'YTDLP_CONFIG': YTDLP_CONFIG
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
