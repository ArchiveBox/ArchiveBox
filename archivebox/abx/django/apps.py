__package__ = 'abx.django'

from django.apps import AppConfig


class ABXConfig(AppConfig):
    name = 'abx'

    def ready(self):
        import abx
        from django.conf import settings
        
        abx.pm.hook.ready(settings=settings)
