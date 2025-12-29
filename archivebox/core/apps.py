__package__ = 'archivebox.core'

from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'archivebox.core'
    label = 'core'

    def ready(self):
        """Register the archivebox.core.admin_site as the main django admin site"""
        from archivebox.core.admin_site import register_admin_site
        register_admin_site()

        # Import models to register state machines with the registry
        from archivebox.core import models  # noqa: F401
