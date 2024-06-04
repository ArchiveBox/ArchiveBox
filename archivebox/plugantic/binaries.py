__package__ = 'archivebox.plugantic'

import sys
import inspect
import importlib
from pathlib import Path


from typing import Any, Optional, Dict, List
from typing_extensions import Self
from subprocess import run, PIPE


from pydantic_core import ValidationError

from pydantic import BaseModel, Field, model_validator, computed_field, field_validator, validate_call, field_serializer

from .binproviders import (
    SemVer,
    BinName,
    BinProviderName,
    HostBinPath,
    BinProvider,
    EnvProvider,
    AptProvider,
    BrewProvider,
    PipProvider,
    ProviderLookupDict,
    bin_name,
    bin_abspath,
    path_is_script,
    path_is_executable,
)


class Binary(BaseModel):
    name: BinName
    description: str = Field(default='')

    providers_supported: List[BinProvider] = Field(default=[EnvProvider()], alias='providers')
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = Field(default={}, alias='overrides')
    
    loaded_provider: Optional[BinProviderName] = Field(default=None, alias='provider')
    loaded_abspath: Optional[HostBinPath] = Field(default=None, alias='abspath')
    loaded_version: Optional[SemVer] = Field(default=None, alias='version')
    
    # bin_filename:  see below
    # is_executable: see below
    # is_script
    # is_valid: see below


    @model_validator(mode='after')
    def validate(self):
        self.loaded_abspath = bin_abspath(self.name) or self.name
        self.description = self.description or self.name
        
        assert self.providers_supported, f'No providers were given for package {self.name}'

        # pull in any overrides from the binproviders
        for provider in self.providers_supported:
            overrides_by_provider = provider.get_providers_for_bin(self.name)
            if overrides_by_provider:
                self.provider_overrides[provider.name] = {
                    **overrides_by_provider,
                    **self.provider_overrides.get(provider.name, {}),
                }
        return self

    @field_validator('loaded_abspath', mode='before')
    def parse_abspath(cls, value: Any):
        return bin_abspath(value)

    @field_validator('loaded_version', mode='before')
    def parse_version(cls, value: Any):
        return value and SemVer(value)

    @field_serializer('provider_overrides', when_used='json')
    def serialize_overrides(self, provider_overrides: Dict[BinProviderName, ProviderLookupDict]) -> Dict[BinProviderName, Dict[str, str]]:
        return {
            provider_name: {
                key: str(val)
                for key, val in overrides.items()
            }
            for provider_name, overrides in provider_overrides.items()
        }

    @computed_field                                                                                           # type: ignore[misc]  # see mypy issue #1362
    @property
    def bin_filename(self) -> BinName:
        if self.is_script:
            # e.g. '.../Python.framework/Versions/3.11/lib/python3.11/sqlite3/__init__.py' -> sqlite
            name = self.name
        elif self.loaded_abspath:
            # e.g. '/opt/homebrew/bin/wget' -> wget
            name = bin_name(self.loaded_abspath)
        else:
            # e.g. 'ytdlp' -> 'yt-dlp'
            name = bin_name(self.name)
        return name

    @computed_field                                                                                           # type: ignore[misc]  # see mypy issue #1362
    @property
    def is_executable(self) -> bool:
        try:
            assert self.loaded_abspath and path_is_executable(self.loaded_abspath)
            return True
        except (ValidationError, AssertionError):
            return False

    @computed_field                                                                                           # type: ignore[misc]  # see mypy issue #1362
    @property
    def is_script(self) -> bool:
        try:
            assert self.loaded_abspath and path_is_script(self.loaded_abspath)
            return True
        except (ValidationError, AssertionError):
            return False

    @computed_field                                                                                           # type: ignore[misc]  # see mypy issue #1362
    @property
    def is_valid(self) -> bool:
        return bool(
            self.name
            and self.loaded_abspath
            and self.loaded_version
            and (self.is_executable or self.is_script)
        )

    @validate_call
    def install(self) -> Self:
        if not self.providers_supported:
            return self

        exc = Exception('No providers were able to install binary', self.name, self.providers_supported)
        for provider in self.providers_supported:
            try:
                installed_bin = provider.install(self.name, overrides=self.provider_overrides.get(provider.name))
                if installed_bin:
                    # print('INSTALLED', self.name, installed_bin)
                    return self.model_copy(update={
                        'loaded_provider': provider.name,
                        'loaded_abspath': installed_bin.abspath,
                        'loaded_version': installed_bin.version,
                    })
            except Exception as err:
                print(err)
                exc = err
        raise exc

    @validate_call
    def load(self, cache=True) -> Self:
        if self.is_valid:
            return self

        if not self.providers_supported:
            return self

        exc = Exception('No providers were able to install binary', self.name, self.providers_supported)
        for provider in self.providers_supported:
            try:
                installed_bin = provider.load(self.name, cache=cache, overrides=self.provider_overrides.get(provider.name))
                if installed_bin:
                    # print('LOADED', provider, self.name, installed_bin)
                    return self.model_copy(update={
                        'loaded_provider': provider.name,
                        'loaded_abspath': installed_bin.abspath,
                        'loaded_version': installed_bin.version,
                    })
            except Exception as err:
                print(err)
                exc = err
        raise exc

    @validate_call
    def load_or_install(self, cache=True) -> Self:
        if self.is_valid:
            return self

        if not self.providers_supported:
            return self

        exc = Exception('No providers were able to install binary', self.name, self.providers_supported)
        for provider in self.providers_supported:
            try:
                installed_bin = provider.load_or_install(self.name, overrides=self.provider_overrides.get(provider.name), cache=cache)
                if installed_bin:
                    # print('LOADED_OR_INSTALLED', self.name, installed_bin)
                    return self.model_copy(update={
                        'loaded_provider': provider.name,
                        'loaded_abspath': installed_bin.abspath,
                        'loaded_version': installed_bin.version,
                    })
            except Exception as err:
                print(err)
                exc = err
        raise exc

    @validate_call
    def exec(self, args=(), pwd='.'):
        assert self.loaded_abspath
        assert self.loaded_version
        return run([self.loaded_abspath, *args], stdout=PIPE, stderr=PIPE, pwd=pwd)




class SystemPythonHelpers:
    @staticmethod
    def get_subdeps() -> str:
        return 'python3 python3-minimal python3-pip python3-virtualenv'

    @staticmethod
    def get_abspath() -> str:
        return sys.executable
    
    @staticmethod
    def get_version() -> str:
        return '{}.{}.{}'.format(*sys.version_info[:3])


class SqliteHelpers:
    @staticmethod
    def get_abspath() -> Path:
        import sqlite3
        importlib.reload(sqlite3)
        return Path(inspect.getfile(sqlite3))

    @staticmethod
    def get_version() -> SemVer:
        import sqlite3
        importlib.reload(sqlite3)
        version = sqlite3.version
        assert version
        return SemVer(version)

class DjangoHelpers:
    @staticmethod
    def get_django_abspath() -> str:
        import django
        return inspect.getfile(django)
    

    @staticmethod
    def get_django_version() -> str:
        import django
        return '{}.{}.{} {} ({})'.format(*django.VERSION)

class YtdlpHelpers:
    @staticmethod
    def get_ytdlp_subdeps() -> str:
        return 'yt-dlp ffmpeg'

    @staticmethod
    def get_ytdlp_version() -> str:
        import yt_dlp
        importlib.reload(yt_dlp)

        version = yt_dlp.version.__version__
        assert version
        return version

class PythonBinary(Binary):
    name: BinName = 'python'

    providers_supported: List[BinProvider] = [
        EnvProvider(
            subdeps_provider={'python': 'plugantic.binaries.SystemPythonHelpers.get_subdeps'},
            abspath_provider={'python': 'plugantic.binaries.SystemPythonHelpers.get_abspath'},
            version_provider={'python': 'plugantic.binaries.SystemPythonHelpers.get_version'},
        ),
    ]

class SqliteBinary(Binary):
    name: BinName = 'sqlite'
    providers_supported: List[BinProvider] = [
        EnvProvider(
            version_provider={'sqlite': 'plugantic.binaries.SqliteHelpers.get_version'},
            abspath_provider={'sqlite': 'plugantic.binaries.SqliteHelpers.get_abspath'},
        ),
    ]

class DjangoBinary(Binary):
    name: BinName = 'django'
    providers_supported: List[BinProvider] = [
        EnvProvider(
            abspath_provider={'django': 'plugantic.binaries.DjangoHelpers.get_django_abspath'},
            version_provider={'django': 'plugantic.binaries.DjangoHelpers.get_django_version'},
        ),
    ]





class YtdlpBinary(Binary):
    name: BinName = 'yt-dlp'
    providers_supported: List[BinProvider] = [
        # EnvProvider(),
        PipProvider(version_provider={'yt-dlp': 'plugantic.binaries.YtdlpHelpers.get_ytdlp_version'}),
        BrewProvider(subdeps_provider={'yt-dlp': 'plugantic.binaries.YtdlpHelpers.get_ytdlp_subdeps'}),
        # AptProvider(subdeps_provider={'yt-dlp': lambda: 'yt-dlp ffmpeg'}),
    ]


class WgetBinary(Binary):
    name: BinName = 'wget'
    providers_supported: List[BinProvider] = [EnvProvider(), AptProvider()]


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
