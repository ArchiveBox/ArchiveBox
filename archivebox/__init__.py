__package__ = 'archivebox'

import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent           # archivebox source code dir
DATA_DIR = Path(os.curdir).resolve()                    # archivebox user data dir
ARCHIVE_DIR = DATA_DIR / 'archive'                      # archivebox snapshot data dir

# make sure PACKAGE_DIR is in sys.path so we can import all subfolders
# without necessarily waiting for django to load them thorugh INSTALLED_APPS
if str(PACKAGE_DIR) not in sys.path:
    sys.path.append(str(PACKAGE_DIR))


from .config.constants import CONSTANTS, VERSION, PACKAGE_DIR, DATA_DIR, ARCHIVE_DIR   # noqa

os.environ['OUTPUT_DIR'] = str(DATA_DIR)
os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'

# print('INSTALLING MONKEY PATCHES')
from .monkey_patches import *                    # noqa
# print('DONE INSTALLING MONKEY PATCHES')

# print('LOADING VENDOR LIBRARIES')
from .vendor import load_vendored_libs           # noqa
load_vendored_libs()
# print('DONE LOADING VENDOR LIBRARIES')

__version__ = VERSION
__author__ = 'Nick Sweeting'
__license__ = 'MIT'
