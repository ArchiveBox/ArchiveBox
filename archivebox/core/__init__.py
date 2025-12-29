__package__ = 'archivebox.core'
__order__ = 100


def register_admin(admin_site):
    """Register the core.models views (Snapshot, ArchiveResult, Tag, etc.) with the admin site"""
    from archivebox.core.admin import register_admin as do_register
    do_register(admin_site)


def get_CONFIG():
    from archivebox.config.common import (
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
