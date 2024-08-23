__package__ = 'archivebox.plugantic'

import sys
import inspect
import importlib
from pathlib import Path


from typing import Any, Optional, Dict, List
from typing_extensions import Self
from subprocess import run, PIPE

from pydantic_pkgr import Binary, SemVer, BinName, BinProvider, EnvProvider, AptProvider, BrewProvider, PipProvider, BinProviderName, ProviderLookupDict

import django
from django.db.backends.sqlite3.base import Database as sqlite3




def get_ytdlp_version() -> str:
    import yt_dlp
    return yt_dlp.version.__version__




class YtdlpBinary(Binary):
    name: BinName = 'yt-dlp'
    providers_supported: List[BinProvider] = [
        EnvProvider(),
        PipProvider(),
        BrewProvider(),
        AptProvider(),
    ]
    provider_overrides:  Dict[BinProviderName, ProviderLookupDict] = {
        'pip': {
            'version': get_ytdlp_version,
        },
        'brew': {
            'subdeps': lambda: 'yt-dlp ffmpeg',
        },
        'apt': {
            'subdeps': lambda: 'yt-dlp ffmpeg',
        }
    }

class WgetBinary(Binary):
    name: BinName = 'wget'
    providers_supported: List[BinProvider] = [EnvProvider(), AptProvider(), BrewProvider()]


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
