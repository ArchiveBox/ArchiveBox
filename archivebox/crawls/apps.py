from django.apps import AppConfig


class CrawlsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "archivebox.crawls"
    label = "crawls"

    def ready(self):
        """Import models to register state machines with the registry"""
        import sys

        # Skip during makemigrations to avoid premature state machine access
        if 'makemigrations' not in sys.argv:
            from archivebox.crawls.models import CrawlMachine  # noqa: F401
