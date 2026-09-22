__package__ = "archivebox.plugins"

from django.apps import AppConfig


class PluginsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "archivebox.plugins"
    verbose_name = "Plugins"
