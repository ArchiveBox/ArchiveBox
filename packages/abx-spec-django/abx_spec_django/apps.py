__package__ = 'abx_spec_django'

from django.apps import AppConfig

import abx


class ABXConfig(AppConfig):
    name = 'abx_spec_django'

    def ready(self):
        from django.conf import settings
        
        abx.pm.hook.ready(settings=settings)
