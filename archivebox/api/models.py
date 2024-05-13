__package__ = 'archivebox.api'

import uuid
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from signal_webhooks.models import WebhookBase

from django_stubs_ext.db.models import TypedModelMeta

from abid_utils.models import ABIDModel


def generate_secret_token() -> str:
    # returns cryptographically secure string with len() == 32
    return secrets.token_hex(16)


class APIToken(ABIDModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=True)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token = models.CharField(max_length=32, default=generate_secret_token, unique=True)
    
    created = models.DateTimeField(auto_now_add=True)
    expires = models.DateTimeField(null=True, blank=True)

    class Meta(TypedModelMeta):
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"

    def __str__(self) -> str:
        return self.token

    def __repr__(self) -> str:
        return f'<APIToken user={self.user.username} token=************{self.token[-4:]}>'

    def __json__(self) -> dict:
        return {
            "TYPE":             "APIToken",    
            "id":               str(self.id),
            "user_id":          str(self.user.id),
            "user_username":    self.user.username,
            "token":            self.token,
            "created":          self.created.isoformat(),
            "expires":          self.expires_as_iso8601,
        }

    @property
    def expires_as_iso8601(self):
        """Returns the expiry date of the token in ISO 8601 format or a date 100 years in the future if none."""
        expiry_date = self.expires or (timezone.now() + timedelta(days=365 * 100))

        return expiry_date.isoformat()

    def is_valid(self, for_date=None):
        for_date = for_date or timezone.now()

        if self.expires and self.expires < for_date:
            return False

        return True






# monkey patch django-signals-webhooks to change how it shows up in Admin UI

class OutboundWebhook(ABIDModel, WebhookBase):
    """
    Model used in place of (extending) signals_webhooks.models.WebhookModel. Swapped using:
        settings.SIGNAL_WEBHOOKS_CUSTOM_MODEL = 'api.models.OutboundWebhook'
    """
    ID_PREFIX = 'whk'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=True)

    WebhookBase._meta.get_field('name').help_text = (
        'Give your webhook a descriptive name (e.g. Notify ACME Slack channel of any new ArchiveResults).')
    WebhookBase._meta.get_field('signal').help_text = (
        'The type of event the webhook should fire for (e.g. Create, Update, Delete).')
    WebhookBase._meta.get_field('ref').help_text = (
        'Dot import notation of the model the webhook should fire for (e.g. core.models.Snapshot or core.models.ArchiveResult).')
    WebhookBase._meta.get_field('endpoint').help_text = (
        'External URL to POST the webhook notification to (e.g. https://someapp.example.com/webhook/some-webhook-receiver).')

    class Meta(WebhookBase.Meta):
        verbose_name = 'API Outbound Webhook'
