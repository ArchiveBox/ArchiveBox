__package__ = 'archivebox.plugins.defaults'



from django.apps import AppConfig


class DefaultsPluginConfig(AppConfig):
    label = "ArchiveBox Defaults"
    name = "defaults"
    
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        print('plugins.defaults.apps.DefaultsPluginConfig.ready')

        from django.conf import settings

        from .settings import register_plugin_settings

        register_plugin_settings(settings, name=self.name)
        
