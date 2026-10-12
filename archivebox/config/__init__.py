"""Minimal import-time config exports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .constants import CONSTANTS as CONSTANTS, CONSTANTS_CONFIG as CONSTANTS_CONFIG
    from .paths import PACKAGE_DIR as PACKAGE_DIR, DATA_DIR as DATA_DIR
    from .version import VERSION as VERSION

__package__ = "archivebox.config"
__order__ = 200


def __getattr__(name: str):
    if name in ("CONSTANTS", "CONSTANTS_CONFIG"):
        from .constants import CONSTANTS, CONSTANTS_CONFIG

        return {"CONSTANTS": CONSTANTS, "CONSTANTS_CONFIG": CONSTANTS_CONFIG}[name]
    if name in ("PACKAGE_DIR", "DATA_DIR"):
        from .paths import PACKAGE_DIR, DATA_DIR

        return {"PACKAGE_DIR": PACKAGE_DIR, "DATA_DIR": DATA_DIR}[name]
    if name == "VERSION":
        from .version import VERSION

        return VERSION
    raise AttributeError(name)


__all__ = ("CONSTANTS", "CONSTANTS_CONFIG", "PACKAGE_DIR", "DATA_DIR", "VERSION")
