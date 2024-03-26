# __package__ = 'archivebox.plugins.defaults'



from django.apps import AppConfig


class DefaultsPluginAppConfig(AppConfig):
    name = "plugins.defaults"

    # label = "ArchiveBox Defaults"
    verbose_name = "Plugin Configuration Defaults"
    
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        print('plugins.defaults.apps.DefaultsPluginConfig.ready')

        from django.conf import settings

        from .settings import register_plugin_settings

        register_plugin_settings(settings, name=self.name)
        
