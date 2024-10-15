__package__ = 'archivebox.core'

from django.apps import AppConfig

import abx


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from core.admin_site import register_admin_site
        register_admin_site()




@abx.hookimpl
def register_admin(admin_site):
    from core.admin import register_admin
    register_admin(admin_site)
