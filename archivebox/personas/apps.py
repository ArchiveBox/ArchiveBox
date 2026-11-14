from django.apps import AppConfig


class PersonasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "archivebox.personas"
    label = "personas"

    def ready(self):
        from abx_plugins.plugins.base.django import register_webhooks

        register_webhooks(self.get_model("Persona"))
