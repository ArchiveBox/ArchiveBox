__package__ = "archivebox.machine"

from django.apps import AppConfig


class MachineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"

    name = "archivebox.machine"
    label = "machine"  # Explicit label for migrations
    verbose_name = "Machine Info"

    def ready(self):
        from abx_plugins.plugins.base.django import register_webhooks
        from archivebox.api.webhook_events import EVENTS

        for model in ("Machine", "NetworkInterface", "Binary"):
            register_webhooks(self.get_model(model))
        register_webhooks(
            self.get_model("Process"),
            events={key: EVENTS[key] for key in ("STARTED", "EXITED")},
            status_events={"running": "STARTED", "exited": "EXITED"},
        )


def register_admin(admin_site):
    from archivebox.machine.admin import register_admin

    register_admin(admin_site)
