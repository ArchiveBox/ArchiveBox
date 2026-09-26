__package__ = "archivebox.api"

from django.apps import AppConfig


class APIConfig(AppConfig):
    name = "archivebox.api"
    label = "api"

    def ready(self):
        from archivebox.api.webhooks import register_delete_webhook_field_loader

        register_delete_webhook_field_loader()


def register_admin(admin_site):
    from archivebox.api.admin import register_admin

    register_admin(admin_site)
