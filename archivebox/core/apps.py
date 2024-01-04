from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'
    # WIP: broken by Django 3.1.2 -> 4.0 migration
    default_auto_field = 'django.db.models.UUIDField'
