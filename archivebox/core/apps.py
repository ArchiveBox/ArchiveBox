__package__ = 'archivebox.core'

from django.apps import AppConfig

import archivebox


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        """Register the archivebox.core.admin_site as the main django admin site"""
        from django.conf import settings
        archivebox.pm.hook.ready(settings=settings)
        
        from core.admin_site import register_admin_site
        register_admin_site()
        


