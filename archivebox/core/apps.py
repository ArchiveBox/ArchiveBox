__package__ = 'archivebox.core'

from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'archivebox.core'
    label = 'core'

    def ready(self):
        """Register the archivebox.core.admin_site as the main django admin site"""
        import sys

        from archivebox.core.admin_site import register_admin_site
        register_admin_site()

        # Import models to register state machines with the registry
        # Skip during makemigrations to avoid premature state machine access
        if 'makemigrations' not in sys.argv:
            from archivebox.core import models  # noqa: F401
