__package__ = 'archivebox.plugantic'

from django.apps import AppConfig

class PluganticConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'plugantic'

    def ready(self) -> None:
        pass
        # from django.conf import settings
        # print(f'[🧩] Detected {len(settings.INSTALLED_PLUGINS)} settings.INSTALLED_PLUGINS to load...')
