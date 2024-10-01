import sys
from typing import List, Optional
from pathlib import Path

from rich import print
from pydantic import InstanceOf, Field, model_validator
from pydantic_pkgr import BinProvider, BinName

from abx.archivebox.base_plugin import BasePlugin, BaseHook
from abx.archivebox.base_configset import BaseConfigSet
from abx.archivebox.base_binary import BaseBinary, env, apt, brew
from abx.archivebox.base_extractor import BaseExtractor, ExtractorName

from archivebox.extractors.wget import wget_output_path


class WgetConfig(BaseConfigSet):

    SAVE_WGET: bool = True
    SAVE_WARC: bool = True
    
    USE_WGET: bool = Field(default=lambda c: c.SAVE_WGET or c.SAVE_WARC)
    
    WGET_BINARY: str = Field(default='wget')
    WGET_ARGS: List[str] = [
        '--no-verbose',
        '--adjust-extension',
        '--convert-links',
        '--force-directories',
        '--backup-converted',
        '--span-hosts',
        '--no-parent',
        '-e', 'robots=off',
    ]
    WGET_EXTRA_ARGS: List[str] = []
    
    WGET_AUTO_COMPRESSION: bool = Field(default=True)
    SAVE_WGET_REQUISITES: bool = Field(default=True)
    WGET_USER_AGENT: str = Field(default='', alias='USER_AGENT')
    WGET_TIMEOUT: int = Field(default=60, alias='TIMEOUT')
    WGET_CHECK_SSL_VALIDITY: bool = Field(default=True, alias='CHECK_SSL_VALIDITY')
    WGET_RESTRICT_FILE_NAMES: str = Field(default='windows', alias='RESTRICT_FILE_NAMES')
    WGET_COOKIES_FILE: Optional[Path] = Field(default=None, alias='COOKIES_FILE')
    
    @model_validator(mode='after')
    def validate_use_ytdlp(self):
        if self.USE_WGET and self.WGET_TIMEOUT < 10:
            print(f'[red][!] Warning: TIMEOUT is set too low! (currently set to TIMEOUT={self.WGET_TIMEOUT} seconds)[/red]', file=sys.stderr)
            print('    wget will fail to archive any sites if set to less than ~20 seconds.', file=sys.stderr)
            print('    (Setting it somewhere over 60 seconds is recommended)', file=sys.stderr)
            print(file=sys.stderr)
            print('    If you want to disable media archiving entirely, set SAVE_MEDIA=False instead:', file=sys.stderr)
            print('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#save_media', file=sys.stderr)
            print(file=sys.stderr)
        return self

WGET_CONFIG = WgetConfig()


class WgetBinary(BaseBinary):
    name: BinName = WGET_CONFIG.WGET_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

WGET_BINARY = WgetBinary()


class WgetExtractor(BaseExtractor):
    name: ExtractorName = 'wget'
    binary: str = WGET_BINARY.name

    def get_output_path(self, snapshot) -> Path | None:
        wget_index_path = wget_output_path(snapshot.as_link())
        if wget_index_path:
            return Path(wget_index_path)
        return None

WGET_EXTRACTOR = WgetExtractor()


class WarcExtractor(BaseExtractor):
    name: ExtractorName = 'warc'
    binary: str = WGET_BINARY.name

    def get_output_path(self, snapshot) -> Path | None:
        warc_files = (snapshot.link_dir / 'warc').glob('*.warc.gz')
        if warc_files:
            return sorted(warc_files, key=lambda x: x.stat().st_size, reverse=True)[0]
        return None


WARC_EXTRACTOR = WarcExtractor()


class WgetPlugin(BasePlugin):
    app_label: str = 'wget'
    verbose_name: str = 'WGET'
    
    hooks: List[InstanceOf[BaseHook]] = [
        WGET_CONFIG,
        WGET_BINARY,
        WGET_EXTRACTOR,
        WARC_EXTRACTOR,
    ]


PLUGIN = WgetPlugin()
DJANGO_APP = PLUGIN.AppConfig
