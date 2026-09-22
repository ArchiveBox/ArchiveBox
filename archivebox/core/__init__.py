__package__ = "archivebox.core"
__order__ = 100


def register_admin(admin_site):
    """Register the core.models views (Snapshot, ArchiveResult, Tag, etc.) with the admin site"""
    from archivebox.core.admin import register_admin as do_register

    do_register(admin_site)
