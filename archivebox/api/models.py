__package__ = 'archivebox.api'

import secrets
from archivebox.uuid_compat import uuid7
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django_stubs_ext.db.models import TypedModelMeta
from signal_webhooks.models import WebhookBase

from archivebox.base_models.models import get_or_create_system_user_pk


def generate_secret_token() -> str:
    return secrets.token_hex(16)


class APIToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    token = models.CharField(max_length=32, default=generate_secret_token, unique=True)
    expires = models.DateTimeField(null=True, blank=True)

    class Meta(TypedModelMeta):
        app_label = 'api'
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"

    def __str__(self) -> str:
        return self.token

    @property
    def token_redacted(self):
        return f'************{self.token[-4:]}'

    def is_valid(self, for_date=None):
        return not self.expires or self.expires >= (for_date or timezone.now())


class OutboundWebhook(WebhookBase):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta(WebhookBase.Meta):
        app_label = 'api'
        verbose_name = 'API Outbound Webhook'

    def __str__(self) -> str:
        return f'[{self.id}] {self.ref} -> {self.endpoint}'
