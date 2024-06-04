__package__ = 'archivebox'

import django_stubs_ext

django_stubs_ext.monkeypatch()


# monkey patch django timezone to add back utc (it was removed in Django 5.0)
import datetime
from django.utils import timezone
timezone.utc = datetime.timezone.utc


# monkey patch django-signals-webhooks to change how it shows up in Admin UI
# from signal_webhooks.apps import DjangoSignalWebhooksConfig
# DjangoSignalWebhooksConfig.verbose_name = 'API'
