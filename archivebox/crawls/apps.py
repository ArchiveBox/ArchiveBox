from django.apps import AppConfig


class CrawlsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "archivebox.crawls"
    label = "crawls"

    def ready(self):
        from abx_plugins.plugins.base.django import register_webhooks
        from archivebox.api.webhook_events import EVENTS

        register_webhooks(
            self.get_model("Crawl"),
            events={key: EVENTS[key] for key in ("BEFORE_QUEUE", "STARTED", "COMPLETED")},
            status_events={"started": "STARTED", "sealed": "COMPLETED"},
        )
        register_webhooks(self.get_model("CrawlSchedule"))
