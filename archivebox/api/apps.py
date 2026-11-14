__package__ = "archivebox.api"

from django.apps import AppConfig


class APIConfig(AppConfig):
    name = "archivebox.api"
    label = "api"

    def ready(self):
        from archivebox.api.webhooks import register_delete_webhook_field_loader
        from archivebox.api.webhook_events import register_lifecycle_signals
        from archivebox.api.webhook_membership import register_membership_signals
        from django.contrib.auth import get_user_model
        from abx_plugins.plugins.base.django import register_webhooks

        # User is supplied by Django; keep its icon on the class like our models.
        get_user_model().emoji = "👤"
        register_webhooks(get_user_model())
        for model in ("APIToken", "OutboundWebhook"):
            register_webhooks(self.get_model(model))
        register_delete_webhook_field_loader()
        register_lifecycle_signals()
        register_membership_signals()


def register_admin(admin_site):
    from archivebox.api.admin import register_admin

    register_admin(admin_site)
