__package__ = 'archivebox.core'

from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        """Register the archivebox.core.admin_site as the main django admin site"""
        from core.admin_site import register_admin_site
        register_admin_site()
