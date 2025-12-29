__package__ = 'archivebox.machine'

from django.apps import AppConfig


class MachineConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'

    name = 'archivebox.machine'
    verbose_name = 'Machine Info'


def register_admin(admin_site):
    from archivebox.machine.admin import register_admin
    register_admin(admin_site)
