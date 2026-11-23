__package__ = "archivebox.api"

import secrets
from archivebox.uuid_compat import CompactUUIDField, uuid7

from django.conf import settings
from django.db import models
from django.utils import timezone
from django_stubs_ext.db.models import TypedModelMeta
from signal_webhooks.models import WebhookBase

from archivebox.base_models.models import ModelWithHealthStats, get_or_create_system_user_pk


def generate_secret_token() -> str:
    return secrets.token_hex(16)


class APIToken(models.Model):
    emoji: str = "🔑"
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    token = models.CharField(max_length=32, default=generate_secret_token, unique=True)
    expires = models.DateTimeField(null=True, blank=True)

    class Meta(TypedModelMeta):
        app_label = "api"
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"

    def __str__(self) -> str:
        return self.token

    @property
    def token_redacted(self):
        return f"************{self.token[-4:]}"

    def is_valid(self, for_date=None):
        return not self.expires or self.expires >= (for_date or timezone.now())


class OutboundWebhook(WebhookBase, ModelWithHealthStats):
    emoji: str = "🪝"
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    # Retain endpoint/token fields for existing HTTP subscriptions. New sequences
    # use actions; credentials remain in WebhookBase's encrypted TokenField.
    endpoint = models.URLField(max_length=2047, blank=True)
    last_success = models.DateTimeField(null=True, blank=True, default=None)
    last_failure = models.DateTimeField(null=True, blank=True, default=None)
    from archivebox.api.webhook_events import signal_choices

    signal = models.CharField(max_length=255, choices=signal_choices)
    actions = models.JSONField(default=list, blank=True)
    folder = models.ForeignKey("core.Folder", null=True, blank=True, on_delete=models.CASCADE)
    any_folder = models.BooleanField(default=False)
    tag = models.ForeignKey("core.Tag", null=True, blank=True, on_delete=models.CASCADE, db_index=False)
    any_tag = models.BooleanField(default=False)
    relationship = models.CharField(max_length=255, blank=True, default="")
    position = models.PositiveIntegerField(default=0)
    stop_processing = models.BooleanField(default=False)
    stop_on_failure = models.BooleanField(default=True)

    class Meta(WebhookBase.Meta):
        app_label = "api"
        verbose_name = "Rule"
        verbose_name_plural = "Rules"
        ordering = ("position", "created_at", "pk")
        constraints = []

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        from signal_webhooks.typing import SignalChoices
        from archivebox.api.webhook_events import RELATIONSHIP_EVENTS, TAG_EVENTS, event_catalog
        from archivebox.api.webhook_actions import validate_actions

        supported = next((model for model in event_catalog() if model["ref"] == self.ref), None)
        if supported is None:
            raise ValidationError({"ref": "Choose an available object type."})
        if self.signal not in {event["key"] for event in supported["events"]} and self.signal not in SignalChoices.values:
            raise ValidationError({"signal": "Choose an event for this object type."})
        membership = self.signal in {"FOLDER_ENTERED", "FOLDER_LEFT"}
        if membership != bool(self.folder_id or self.any_folder) or (self.folder_id and self.any_folder):
            raise ValidationError({"folder": "Choose one folder or Any folder for a folder membership event only."})
        if (self.signal in TAG_EVENTS) != bool(self.tag_id or self.any_tag) or (self.tag_id and self.any_tag):
            raise ValidationError({"tag": "Choose one tag or Any tag for a tag event only."})
        if self.relationship and (
            self.signal not in RELATIONSHIP_EVENTS or self.relationship not in {item["id"] for item in supported["relationships"]}
        ):
            raise ValidationError({"relationship": "Choose a relationship for this object type and event."})
        if membership and self.ref != "archivebox.core.models.Snapshot":
            raise ValidationError({"signal": "Folder membership events apply to snapshots."})
        if self.actions:
            validate_actions(self)
        elif not self.endpoint:
            raise ValidationError({"actions": "Choose at least one action."})

    def __str__(self) -> str:
        return self.name
