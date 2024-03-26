from django.apps import AppConfig


class GalleryDLAppConfig(AppConfig):
    label = "Gallery-DL"
    name = "plugin_gallerydl"
    
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # querying models is ok, but don't fetch rows from DB or perform stateful actions here

        print('√ Loaded GalleryDL Plugin')
