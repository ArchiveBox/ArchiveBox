__package__ = 'abx_plugin_ytdlp'

from typing import List

from pydantic import Field, AliasChoices

from abx_spec_config.base_configset import BaseConfigSet

from archivebox.config.common import ARCHIVING_CONFIG
from archivebox.misc.logging import STDERR


class YtdlpConfig(BaseConfigSet):
    USE_YTDLP: bool                = Field(default=True, validation_alias=AliasChoices('USE_YOUTUBEDL', 'SAVE_MEDIA'))

    YTDLP_BINARY: str              = Field(default='yt-dlp', alias='YOUTUBEDL_BINARY')
    YTDLP_EXTRA_ARGS: List[str]    = Field(default=lambda: [
        '--restrict-filenames',
        '--trim-filenames', '128',
        '--write-description',
        '--write-info-json',
        '--write-annotations',
        '--write-thumbnail',
        '--no-call-home',
        '--write-sub',
        '--write-auto-subs',
        '--convert-subs=srt',
        '--yes-playlist',
        '--continue',
        # This flag doesn't exist in youtube-dl
        # only in yt-dlp
        '--no-abort-on-error',
        # --ignore-errors must come AFTER
        # --no-abort-on-error
        # https://github.com/yt-dlp/yt-dlp/issues/4914
        '--ignore-errors',
        '--geo-bypass',
        '--add-metadata',
        '--format=(bv*+ba/b)[filesize<={}][filesize_approx<=?{}]/(bv*+ba/b)'.format(ARCHIVING_CONFIG.MEDIA_MAX_SIZE, ARCHIVING_CONFIG.MEDIA_MAX_SIZE),
    ], alias='YOUTUBEDL_EXTRA_ARGS')
    
    YTDLP_CHECK_SSL_VALIDITY: bool = Field(default=lambda: ARCHIVING_CONFIG.CHECK_SSL_VALIDITY)
    YTDLP_TIMEOUT: int             = Field(default=lambda: ARCHIVING_CONFIG.MEDIA_TIMEOUT)
    
    def validate(self):
        if self.USE_YTDLP and self.YTDLP_TIMEOUT < 20:
            STDERR.print(f'[red][!] Warning: MEDIA_TIMEOUT is set too low! (currently set to MEDIA_TIMEOUT={self.YTDLP_TIMEOUT} seconds)[/red]')
            STDERR.print('    youtube-dl/yt-dlp will fail to archive any media if set to less than ~20 seconds.')
            STDERR.print('    (Setting it somewhere over 60 seconds is recommended)')
            STDERR.print()
            STDERR.print('    If you want to disable media archiving entirely, set SAVE_MEDIA=False instead:')
            STDERR.print('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#save_media')
            STDERR.print()
        return self


YTDLP_CONFIG = YtdlpConfig()
