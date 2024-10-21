__package__ = 'archivebox.core'

from django.apps import AppConfig

import abx


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        """Register the archivebox.core.admin_site as the main django admin site"""
        from core.admin_site import register_admin_site
        register_admin_site()
        
        abx.pm.hook.ready()




@abx.hookimpl
def register_admin(admin_site):
    """Register the core.models views (Snapshot, ArchiveResult, Tag, etc.) with the admin site"""
    from core.admin import register_admin
    register_admin(admin_site)
