__package__ = 'archivebox.plugins.system'


from django.apps import AppConfig


class SystemPluginAppConfig(AppConfig):
    name = "plugins.system"
    verbose_name = "Host System Configuration"
    
    default_auto_field = "django.db.models.AutoField"

    def ready(self):
        print('plugins.system.apps.SystemPluginConfig.ready')

        from django.conf import settings

        from plugins.defaults.settings import register_plugin_settings

        register_plugin_settings(settings, name=self.name)
        
