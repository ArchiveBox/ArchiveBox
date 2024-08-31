__package__ = 'archivebox.pkg'

import os
import sys
import shutil
import inspect
from pathlib import Path

import django
from django.conf import settings
from django.db.backends.sqlite3.base import Database as sqlite3

from pydantic_pkgr import Binary, BinProvider, BrewProvider, EnvProvider, SemVer
from pydantic_pkgr.binprovider import bin_abspath

from ..config import NODE_BIN_PATH, bin_path

env = EnvProvider(PATH=NODE_BIN_PATH + ':' + os.environ.get('PATH', '/bin'))


LOADED_DEPENDENCIES = {}

for bin_key, dependency in settings.CONFIG.DEPENDENCIES.items():
    # 'PYTHON_BINARY': {
    #     'path': bin_path(config['PYTHON_BINARY']),
    #     'version': config['PYTHON_VERSION'],
    #     'hash': bin_hash(config['PYTHON_BINARY']),
    #     'enabled': True,
    #     'is_valid': bool(config['PYTHON_VERSION']),
    # },
    

    bin_name = settings.CONFIG[bin_key]

    if bin_name.endswith('django/__init__.py'):
        binary_spec = Binary(name='django', providers=[env], provider_overrides={
            'env': {
                'abspath': lambda: Path(inspect.getfile(django)),
                'version': lambda: SemVer('{}.{}.{} {} ({})'.format(*django.VERSION)),
            }
        })
    elif bin_name.endswith('sqlite3/dbapi2.py'):
        binary_spec = Binary(name='sqlite3', providers=[env], provider_overrides={
            'env': {
                'abspath': lambda: Path(inspect.getfile(sqlite3)),
                'version': lambda: SemVer(sqlite3.version),
            }
        })
    elif bin_name.endswith('archivebox'):
        binary_spec = Binary(name='archivebox', providers=[env], provider_overrides={
            'env': {
                'abspath': lambda: shutil.which(str(Path('archivebox').expanduser())),
                'version': lambda: settings.CONFIG.VERSION,
            }
        })
    elif bin_name.endswith('postlight/parser/cli.js'):
        binary_spec = Binary(name='postlight-parser', providers=[env], provider_overrides={
            'env': {
                'abspath': lambda: bin_path('postlight-parser'),
                'version': lambda: SemVer('1.0.0'),
            }
        })
    else:
        binary_spec = Binary(name=bin_name, providers=[env])
    
    try:
        binary = binary_spec.load()
    except Exception as e:
        # print(f"- ❌ Binary {bin_name} failed to load with error: {e}")
        continue

    assert isinstance(binary.loaded_version, SemVer)

    try:
        assert str(binary.loaded_version) == dependency['version'], f"Expected {bin_name} version {dependency['version']}, got {binary.loaded_version}"
        assert str(binary.loaded_respath) == str(bin_abspath(dependency['path']).resolve()), f"Expected {bin_name} abspath {bin_abspath(dependency['path']).resolve()}, got {binary.loaded_respath}"
        assert binary.is_valid == dependency['is_valid'], f"Expected {bin_name} is_valid={dependency['is_valid']}, got {binary.is_valid}"
    except Exception as e:
        pass
        # print(f"WARNING: Error loading {bin_name}: {e}")
        # import ipdb; ipdb.set_trace()
    
    # print(f"- ✅ Binary {bin_name} loaded successfully")
    LOADED_DEPENDENCIES[bin_key] = binary


