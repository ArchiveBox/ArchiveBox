__package__ = 'archivebox.machine'

from django.apps import AppConfig


class MachineConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    
    name = 'machine'
    verbose_name = 'Machine Info'
