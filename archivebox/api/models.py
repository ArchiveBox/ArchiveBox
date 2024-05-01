__package__ = 'archivebox.api'

import uuid
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from django_stubs_ext.db.models import TypedModelMeta


def generate_secret_token() -> str:
    # returns cryptographically secure string with len() == 32
    return secrets.token_hex(16)


class APIToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

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

