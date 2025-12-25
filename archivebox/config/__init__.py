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
    """Module-level __getattr__ for lazy config loading."""
    
    # Timeout settings
    if name == 'TIMEOUT':
        cfg, _ = _get_config()
        return cfg.TIMEOUT
    if name == 'MEDIA_TIMEOUT':
        cfg, _ = _get_config()
        return cfg.MEDIA_TIMEOUT
    
    # SSL/Security settings
    if name == 'CHECK_SSL_VALIDITY':
        cfg, _ = _get_config()
        return cfg.CHECK_SSL_VALIDITY
    
    # Storage settings  
    if name == 'RESTRICT_FILE_NAMES':
        _, storage = _get_config()
        return storage.RESTRICT_FILE_NAMES
    
    # User agent / cookies
    if name == 'COOKIES_FILE':
        cfg, _ = _get_config()
        return cfg.COOKIES_FILE
    if name == 'USER_AGENT':
        cfg, _ = _get_config()
        return cfg.USER_AGENT
    if name == 'CURL_USER_AGENT':
        cfg, _ = _get_config()
        return cfg.USER_AGENT
    if name == 'WGET_USER_AGENT':
        cfg, _ = _get_config()
        return cfg.USER_AGENT
    if name == 'CHROME_USER_AGENT':
        cfg, _ = _get_config()
        return cfg.USER_AGENT
    
    # Archive method toggles (SAVE_*)
    if name == 'SAVE_TITLE':
        return True
    if name == 'SAVE_FAVICON':
        return True
    if name == 'SAVE_WGET':
        return True
    if name == 'SAVE_WARC':
        return True
    if name == 'SAVE_WGET_REQUISITES':
        return True
    if name == 'SAVE_SINGLEFILE':
        return True
    if name == 'SAVE_READABILITY':
        return True
    if name == 'SAVE_MERCURY':
        return True
    if name == 'SAVE_HTMLTOTEXT':
        return True
    if name == 'SAVE_PDF':
        return True
    if name == 'SAVE_SCREENSHOT':
        return True
    if name == 'SAVE_DOM':
        return True
    if name == 'SAVE_HEADERS':
        return True
    if name == 'SAVE_GIT':
        return True
    if name == 'SAVE_MEDIA':
        return True
    if name == 'SAVE_ARCHIVE_DOT_ORG':
        return True
    
    # Extractor-specific settings
    if name == 'RESOLUTION':
        cfg, _ = _get_config()
        return cfg.RESOLUTION
    if name == 'GIT_DOMAINS':
        return 'github.com,bitbucket.org,gitlab.com,gist.github.com,codeberg.org,gitea.com,git.sr.ht'
    if name == 'MEDIA_MAX_SIZE':
        cfg, _ = _get_config()
        return cfg.MEDIA_MAX_SIZE
    if name == 'FAVICON_PROVIDER':
        return 'https://www.google.com/s2/favicons?domain={}'
    
    # Binary paths (use shutil.which for detection)
    if name == 'CURL_BINARY':
        return shutil.which('curl') or 'curl'
    if name == 'WGET_BINARY':
        return shutil.which('wget') or 'wget'
    if name == 'GIT_BINARY':
        return shutil.which('git') or 'git'
    if name == 'YOUTUBEDL_BINARY':
        return shutil.which('yt-dlp') or shutil.which('youtube-dl') or 'yt-dlp'
    if name == 'CHROME_BINARY':
        for chrome in ['chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable', 'chrome']:
            path = shutil.which(chrome)
            if path:
                return path
        return 'chromium'
    if name == 'NODE_BINARY':
        return shutil.which('node') or 'node'
    if name == 'SINGLEFILE_BINARY':
        return shutil.which('single-file') or shutil.which('singlefile') or 'single-file'
    if name == 'READABILITY_BINARY':
        return shutil.which('readability-extractor') or 'readability-extractor'
    if name == 'MERCURY_BINARY':
        return shutil.which('mercury-parser') or shutil.which('postlight-parser') or 'mercury-parser'
    
    # Binary versions (return placeholder, actual version detection happens elsewhere)
    if name == 'CURL_VERSION':
        return 'curl'
    if name == 'WGET_VERSION':
        return 'wget'
    if name == 'GIT_VERSION':
        return 'git'
    if name == 'YOUTUBEDL_VERSION':
        return 'yt-dlp'
    if name == 'CHROME_VERSION':
        return 'chromium'
    if name == 'SINGLEFILE_VERSION':
        return 'singlefile'
    if name == 'READABILITY_VERSION':
        return 'readability'
    if name == 'MERCURY_VERSION':
        return 'mercury'
    
    # Binary arguments
    if name == 'CURL_ARGS':
        return ['--silent', '--location', '--compressed']
    if name == 'WGET_ARGS':
        return [
            '--no-verbose',
            '--adjust-extension',
            '--convert-links',
            '--force-directories',
            '--backup-converted',
            '--span-hosts',
            '--no-parent',
            '-e', 'robots=off',
        ]
    if name == 'GIT_ARGS':
        return ['--recursive']
    if name == 'YOUTUBEDL_ARGS':
        cfg, _ = _get_config()
        return [
            '--write-description',
            '--write-info-json',
            '--write-annotations',
            '--write-thumbnail',
            '--no-call-home',
            '--write-sub',
            '--write-auto-subs',
            '--convert-subs=srt',
            '--yes-playlist',
            '--continue',
            '--no-abort-on-error',
            '--ignore-errors',
            '--geo-bypass',
            '--add-metadata',
            f'--format=(bv*+ba/b)[filesize<={cfg.MEDIA_MAX_SIZE}][filesize_approx<=?{cfg.MEDIA_MAX_SIZE}]/(bv*+ba/b)',
        ]
    if name == 'SINGLEFILE_ARGS':
        return None  # Uses defaults
    if name == 'CHROME_ARGS':
        return []
    
    # Other settings
    if name == 'WGET_AUTO_COMPRESSION':
        return True
    if name == 'DEPENDENCIES':
        return {}  # Legacy, not used anymore
    
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
    return {
        'SHELL_CONFIG': SHELL_CONFIG,
        'STORAGE_CONFIG': STORAGE_CONFIG,
        'GENERAL_CONFIG': GENERAL_CONFIG,
        'SERVER_CONFIG': SERVER_CONFIG,
        'ARCHIVING_CONFIG': ARCHIVING_CONFIG,
        'SEARCHBACKEND_CONFIG': SEARCH_BACKEND_CONFIG,
    }
