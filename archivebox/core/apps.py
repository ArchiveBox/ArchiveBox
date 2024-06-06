__package__ = 'archivebox.core'

from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        # register our custom admin as the primary django admin
        from django.contrib import admin
        from django.contrib.admin import sites
        from core.admin import archivebox_admin

        admin.site = archivebox_admin
        sites.site = archivebox_admin


        # register signal handlers
        from .auth import register_signals

        register_signals()



# from django.contrib.admin.apps import AdminConfig
# class CoreAdminConfig(AdminConfig):
#     default_site = "core.admin.get_admin_site"
