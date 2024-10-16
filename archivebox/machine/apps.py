__package__ = 'archivebox.machine'

from django.apps import AppConfig

import abx


class MachineConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    
    name = 'machine'
    verbose_name = 'Machine Info'


@abx.hookimpl
def register_admin(admin_site):
    from machine.admin import register_admin
    register_admin(admin_site)
