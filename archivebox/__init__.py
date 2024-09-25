__package__ = 'archivebox'

# print('INSTALLING MONKEY PATCHES')

from .monkey_patches import *

import os
import importlib
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent    # archivebox source code dir
DATA_DIR = Path(os.curdir).resolve()             # archivebox user data dir


def _detect_installed_version():
    try:
        return importlib.metadata.version(__package__ or 'archivebox')
    except importlib.metadata.PackageNotFoundError:
        try:
            pyproject_config = (PACKAGE_DIR / 'pyproject.toml').read_text()
            for line in pyproject_config:
                if line.startswith('version = '):
                    return line.split(' = ', 1)[-1].strip('"')
        except FileNotFoundError:
            # building docs, pyproject.toml is not available
            return 'dev'

    raise Exception('Failed to detect installed archivebox version!')


__version__ = _detect_installed_version()

# print('DONE INSTALLING MONKEY PATCHES')
