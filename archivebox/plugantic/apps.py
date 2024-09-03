__package__ = 'archivebox.plugantic'

import json
import importlib

from django.apps import AppConfig

class PluganticConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'plugantic'

    def ready(self) -> None:
        from django.conf import settings

        print(f'[🧩] Detected {len(settings.INSTALLED_PLUGINS)} settings.INSTALLED_PLUGINS to load...')
