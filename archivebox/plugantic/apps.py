import importlib
from django.apps import AppConfig


class PluganticConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'plugantic'

    def ready(self) -> None:
        from django.conf import settings
        from .plugins import PLUGINS

        for plugin_name in settings.INSTALLED_PLUGINS.keys():
            lib = importlib.import_module(f'{plugin_name}.apps')
            if hasattr(lib, 'PLUGINS'):
                for plugin_instance in lib.PLUGINS:
                    PLUGINS.append(plugin_instance)
