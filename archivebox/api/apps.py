__package__ = 'archivebox.api'

from django.apps import AppConfig


class APIConfig(AppConfig):
    name = 'api'


def register_admin(admin_site):
    from api.admin import register_admin
    register_admin(admin_site)
