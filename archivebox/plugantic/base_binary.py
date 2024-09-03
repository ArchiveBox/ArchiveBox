__package__ = 'archivebox.plugantic'

import sys
import inspect
import importlib
from pathlib import Path


from typing import Any, Optional, Dict, List
from typing_extensions import Self
from subprocess import run, PIPE

from pydantic import Field, InstanceOf
from pydantic_pkgr import Binary, SemVer, BinName, BinProvider, EnvProvider, AptProvider, BrewProvider, PipProvider, BinProviderName, ProviderLookupDict
from pydantic_pkgr.binprovider import HostBinPath

import django
from django.core.cache import cache
from django.db.backends.sqlite3.base import Database as sqlite3


class BaseBinProvider(BinProvider):
    # def on_get_abspath(self, bin_name: BinName, **context) -> Optional[HostBinPath]:
    #     Class = super()
    #     get_abspath_func = lambda: Class.on_get_abspath(bin_name, **context)
    #     # return cache.get_or_set(f'bin:abspath:{bin_name}', get_abspath_func)
    #     return get_abspath_func()
    
    # def on_get_version(self, bin_name: BinName, abspath: Optional[HostBinPath]=None, **context) -> SemVer | None:
    #     Class = super()
    #     get_version_func = lambda: Class.on_get_version(bin_name, abspath, **context)
    #     # return cache.get_or_set(f'bin:version:{bin_name}:{abspath}', get_version_func)
    #     return get_version_func()

    def register(self, settings, parent_plugin=None):
        if settings is None:
            from django.conf import settings as django_settings
            settings = django_settings

        self._plugin = parent_plugin                                      # for debugging only, never rely on this!
        settings.BINPROVIDERS[self.name] = self


class BaseBinary(Binary):
    binproviders_supported: List[InstanceOf[BinProvider]] = Field(default_factory=list, alias='binproviders')

    def register(self, settings, parent_plugin=None):
        if settings is None:
            from django.conf import settings as django_settings
            settings = django_settings

        self._plugin = parent_plugin                                      # for debugging only, never rely on this!
        settings.BINARIES[self.name] = self

# def get_ytdlp_version() -> str:
#     import yt_dlp
#     return yt_dlp.version.__version__




# class YtdlpBinary(Binary):
#     name: BinName = 'yt-dlp'
#     providers_supported: List[BinProvider] = [
#         EnvProvider(),
#         PipProvider(),
#         BrewProvider(),
#         AptProvider(),
#     ]
#     provider_overrides:  Dict[BinProviderName, ProviderLookupDict] = {
#         'pip': {
#             'version': get_ytdlp_version,
#         },
#         'brew': {
#             'subdeps': lambda: 'yt-dlp ffmpeg',
#         },
#         'apt': {
#             'subdeps': lambda: 'yt-dlp ffmpeg',
#         }
#     }

# class WgetBinary(Binary):
#     name: BinName = 'wget'
#     providers_supported: List[BinProvider] = [EnvProvider(), AptProvider(), BrewProvider()]


# if __name__ == '__main__':
#     PYTHON_BINARY = PythonBinary()
#     SQLITE_BINARY = SqliteBinary()
#     DJANGO_BINARY = DjangoBinary()
#     WGET_BINARY = WgetBinary()
#     YTDLP_BINARY = YtdlpPBinary()

#     print('-------------------------------------DEFINING BINARIES---------------------------------')
#     print(PYTHON_BINARY)
#     print(SQLITE_BINARY)
#     print(DJANGO_BINARY)
#     print(WGET_BINARY)
#     print(YTDLP_BINARY)
