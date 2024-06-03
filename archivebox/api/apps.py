__package__ = 'archivebox.api'

from django.apps import AppConfig



class APIConfig(AppConfig):
    name = 'api'

    def ready(self):
        pass
