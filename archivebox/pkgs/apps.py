__package__ = 'archivebox.pkgs'

from django.apps import AppConfig


class PkgsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pkgs'

    def ready(self):
        from .settings import LOADED_DEPENDENCIES

        # print(LOADED_DEPENDENCIES)
        