__package__ = "archivebox.search"

from django.apps import AppConfig


class SearchConfig(AppConfig):
    """Register search templates and admin integration with Django."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "archivebox.search"
    verbose_name = "Search"
