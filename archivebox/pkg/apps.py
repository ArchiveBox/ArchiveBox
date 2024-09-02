__package__ = 'archivebox.pkg'

from django.apps import AppConfig


class PkgsConfig(AppConfig):
    name = 'pkg'
    verbose_name = 'Package Management'
    
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from .settings import LOADED_DEPENDENCIES

        # print(LOADED_DEPENDENCIES)
        