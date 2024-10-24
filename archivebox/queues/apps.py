from django.apps import AppConfig

import abx


class QueuesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'queues'


@abx.hookimpl
def register_admin(admin_site):
    from queues.admin import register_admin
    register_admin(admin_site)
