__package__ = 'archivebox.machine'

from django.apps import AppConfig


class MachineConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'

    name = 'archivebox.machine'
    label = 'machine'  # Explicit label for migrations
    verbose_name = 'Machine Info'

    def ready(self):
        """Import models to register state machines with the registry"""
        import sys

        # Skip during makemigrations to avoid premature state machine access
        if 'makemigrations' not in sys.argv:
            from archivebox.machine import models  # noqa: F401


def register_admin(admin_site):
    from archivebox.machine.admin import register_admin
    register_admin(admin_site)
