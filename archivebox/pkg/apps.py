__package__ = 'archivebox.pkg'

from django.apps import AppConfig


class PkgsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pkg'

    def ready(self):
        from .settings import LOADED_DEPENDENCIES

        # print(LOADED_DEPENDENCIES)
        