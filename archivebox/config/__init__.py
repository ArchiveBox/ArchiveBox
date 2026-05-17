"""Minimal import-time config exports."""

__package__ = "archivebox.config"
__order__ = 200

from .paths import (
    PACKAGE_DIR,
    DATA_DIR,
)
from .constants import CONSTANTS, CONSTANTS_CONFIG, PACKAGE_DIR, DATA_DIR  # noqa
from .version import VERSION  # noqa
