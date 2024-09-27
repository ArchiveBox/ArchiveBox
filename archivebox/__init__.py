__package__ = 'archivebox'


# print('INSTALLING MONKEY PATCHES')
from .monkey_patches import *                    # noqa
# print('DONE INSTALLING MONKEY PATCHES')


import os
import sys
import importlib.metadata
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent    # archivebox source code dir
DATA_DIR = Path(os.curdir).resolve()             # archivebox user data dir
ARCHIVE_DIR = DATA_DIR / 'archive'

# make sure PACKAGE_DIR is in sys.path so we can import all subfolders
# without necessarily waiting for django to load them thorugh INSTALLED_APPS
if str(PACKAGE_DIR) not in sys.path:
    sys.path.append(str(PACKAGE_DIR))

# load fallback libraries from vendor dir
from .vendor import load_vendored_libs
load_vendored_libs()


os.environ['OUTPUT_DIR'] = str(DATA_DIR)
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'


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

VERSION = _detect_installed_version()

__version__ = VERSION


from .constants import CONSTANTS
