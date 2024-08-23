import sys
import inspect
from typing import List, Dict, Any, Optional
from pathlib import Path

import django
from django.apps import AppConfig
from django.core.checks import Tags, Warning, register
from django.db.backends.sqlite3.base import Database as sqlite3

from pydantic import (
    Field,
    SerializeAsAny,
)

from pydantic_pkgr import BinProvider, BinProviderName, ProviderLookupDict, BinName, Binary, EnvProvider, NpmProvider

from plugantic.extractors import Extractor, ExtractorName
from plugantic.plugins import Plugin
from plugantic.configs import ConfigSet, ConfigSectionName
from plugantic.replayers import Replayer


class PythonBinary(Binary):
    name: BinName = 'python'

    providers_supported: List[BinProvider] = [EnvProvider()]
    provider_overrides: Dict[str, Any] = {
        'env': {
            'subdeps': \
                lambda: 'python3 python3-minimal python3-pip python3-virtualenv',
            'abspath': \
                lambda: sys.executable,
            'version': \
                lambda: '{}.{}.{}'.format(*sys.version_info[:3]),
        },
    }

class SqliteBinary(Binary):
    name: BinName = 'sqlite'
    providers_supported: List[BinProvider] = [EnvProvider()]
    provider_overrides:  Dict[BinProviderName, ProviderLookupDict] = {
        'env': {
            'abspath': \
                lambda: inspect.getfile(sqlite3),
            'version': \
                lambda: sqlite3.version,
        },
    }

class DjangoBinary(Binary):
    name: BinName = 'django'

    providers_supported: List[BinProvider] = [EnvProvider()]
    provider_overrides:  Dict[BinProviderName, ProviderLookupDict] = {
        'env': {
            'abspath': \
                lambda: inspect.getfile(django),
            'version': \
                lambda: django.VERSION[:3],
        },
    }


class BasicReplayer(Replayer):
    name: str = 'basic'


class BasePlugin(Plugin):
    name: str = 'base'
    configs: List[SerializeAsAny[ConfigSet]] = []
    binaries: List[SerializeAsAny[Binary]] = [PythonBinary(), SqliteBinary(), DjangoBinary()]
    extractors: List[SerializeAsAny[Extractor]] = []
    replayers: List[SerializeAsAny[Replayer]] = [BasicReplayer()]


PLUGINS = [BasePlugin()]


class BaseConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'builtin_plugins.base'
