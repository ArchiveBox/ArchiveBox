from django.apps import AppConfig


class ABXConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'abx'

    def ready(self):
        import abx
        from django.conf import settings
        
        abx.pm.hook.ready(settings=settings)
