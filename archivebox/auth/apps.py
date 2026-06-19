__package__ = "archivebox.auth"

from django.apps import AppConfig


class AuthConfig(AppConfig):
    name = "archivebox.auth"
    label = "archivebox_auth"
    verbose_name = "ArchiveBox Auth"

    def ready(self):
        # Connect signal handlers
        from archivebox.auth import signals  # noqa: F401
