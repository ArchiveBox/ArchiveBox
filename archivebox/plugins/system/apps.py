# __package__ = 'archivebox.plugins.system'


from django.apps import AppConfig


class SystemPluginConfig(AppConfig):
    label = "ArchiveBox System"
    name = "system"
    
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        print('plugins.system.apps.SystemPluginConfig.ready')

        from django.conf import settings

        from .settings import register_plugin_settings

        register_plugin_settings(settings, name=self.name)
        
