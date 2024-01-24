from django.apps import AppConfig


class CoreAppConfig(AppConfig):
    name = 'core'
    # label = 'Archive Data'
    verbose_name = "Archive Data"

    # WIP: broken by Django 3.1.2 -> 4.0 migration
    default_auto_field = 'django.db.models.UUIDField'
