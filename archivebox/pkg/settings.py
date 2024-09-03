__package__ = 'archivebox.pkg'

import os
import sys
import shutil
import inspect
from pathlib import Path

import django
from django.conf import settings
from django.db.backends.sqlite3.base import Database as sqlite3

from pydantic_pkgr import Binary, BinProvider, BrewProvider, PipProvider, NpmProvider, AptProvider, EnvProvider, SemVer
from pydantic_pkgr.binprovider import bin_abspath

from ..config import NODE_BIN_PATH, bin_path

apt = AptProvider()
brew = BrewProvider()
env = EnvProvider(PATH=os.environ.get('PATH', '/bin'))

# Defined in their own plugins:
#pip = PipProvider(PATH=str(Path(sys.executable).parent))
#npm = NpmProvider(PATH=NODE_BIN_PATH)

LOADED_DEPENDENCIES = {}

for bin_name, binary_spec in settings.BINARIES.items():
    try:
        settings.BINARIES[bin_name] = binary_spec.load()
    except Exception as e:
        # print(f"- ❌ Binary {bin_name} failed to load with error: {e}")
        continue
