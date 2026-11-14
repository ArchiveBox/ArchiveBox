from django.apps import AppConfig


class ImportersConfig(AppConfig):
    name = "archivebox.importers"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from abx_plugins.plugins.base.django import register_webhooks
        from archivebox.api.webhook_events import EVENTS

        register_webhooks(self.get_model("ImporterSource"))
        register_webhooks(
            self.get_model("ImporterRun"),
            events={key: EVENTS[key] for key in ("STARTED", "COMPLETED")},
            status_events={"running": "STARTED", **dict.fromkeys(("succeeded", "failed", "needs_login", "cancelled"), "COMPLETED")},
        )
