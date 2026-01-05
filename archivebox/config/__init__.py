"""
ArchiveBox config exports.

This module provides backwards-compatible config exports for extractors
and other modules that expect to import config values directly.
"""

__package__ = 'archivebox.config'
__order__ = 200

import shutil
from pathlib import Path
from typing import Dict, List, Optional

from .paths import (
    PACKAGE_DIR,                                    # noqa
    DATA_DIR,                                       # noqa
    ARCHIVE_DIR,                                    # noqa
)
from .constants import CONSTANTS, CONSTANTS_CONFIG, PACKAGE_DIR, DATA_DIR, ARCHIVE_DIR      # noqa
from .version import VERSION                        # noqa


###############################################################################
# Config value exports for extractors
# These provide backwards compatibility with extractors that import from ..config
###############################################################################

def _get_config():
    """Lazy import to avoid circular imports."""
    from .common import ARCHIVING_CONFIG, STORAGE_CONFIG
    return ARCHIVING_CONFIG, STORAGE_CONFIG

# Direct exports (evaluated at import time for backwards compat)
# These are recalculated each time the module attribute is accessed

def __getattr__(name: str):
    """
    Module-level __getattr__ for lazy config loading.

    Only provides backwards compatibility for GENERIC/SHARED config.
    Plugin-specific config (binaries, args, toggles) should come from plugin config.json files.
    """

    # Generic timeout settings (used by multiple plugins)
    if name == 'TIMEOUT':
        cfg, _ = _get_config()
        return cfg.TIMEOUT

    # Generic SSL/Security settings (used by multiple plugins)
    if name == 'CHECK_SSL_VALIDITY':
        cfg, _ = _get_config()
        return cfg.CHECK_SSL_VALIDITY

    # Generic storage settings (used by multiple plugins)
    if name == 'RESTRICT_FILE_NAMES':
        _, storage = _get_config()
        return storage.RESTRICT_FILE_NAMES

    # Generic user agent / cookies (used by multiple plugins)
    if name == 'COOKIES_FILE':
        cfg, _ = _get_config()
        return cfg.COOKIES_FILE
    if name == 'USER_AGENT':
        cfg, _ = _get_config()
        return cfg.USER_AGENT

    # Generic resolution settings (used by multiple plugins)
    if name == 'RESOLUTION':
        cfg, _ = _get_config()
        return cfg.RESOLUTION

    # Allowlist/Denylist patterns (compiled regexes)
    if name == 'SAVE_ALLOWLIST_PTN':
        cfg, _ = _get_config()
        return cfg.SAVE_ALLOWLIST_PTNS
    if name == 'SAVE_DENYLIST_PTN':
        cfg, _ = _get_config()
        return cfg.SAVE_DENYLIST_PTNS

    raise AttributeError(f"module 'archivebox.config' has no attribute '{name}'")


# Re-export common config classes for direct imports
def get_CONFIG():
    """Get all config sections as a dict."""
    from .common import (
        SHELL_CONFIG,
        STORAGE_CONFIG,
        GENERAL_CONFIG,
        SERVER_CONFIG,
        ARCHIVING_CONFIG,
        SEARCH_BACKEND_CONFIG,
    )
    from .ldap import LDAP_CONFIG
    return {
        'SHELL_CONFIG': SHELL_CONFIG,
        'STORAGE_CONFIG': STORAGE_CONFIG,
        'GENERAL_CONFIG': GENERAL_CONFIG,
        'SERVER_CONFIG': SERVER_CONFIG,
        'ARCHIVING_CONFIG': ARCHIVING_CONFIG,
        'SEARCHBACKEND_CONFIG': SEARCH_BACKEND_CONFIG,
        'LDAP_CONFIG': LDAP_CONFIG,
    }
