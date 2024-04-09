import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

def hex_uuid():
    return uuid.uuid4().hex


class Token(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tokens"
    )
    token = models.CharField(max_length=32, default=hex_uuid, unique=True)
    created = models.DateTimeField(auto_now_add=True)
    expiry = models.DateTimeField(null=True, blank=True)

    @property
    def expiry_as_iso8601(self):
        """Returns the expiry date of the token in ISO 8601 format or a date 100 years in the future if none."""
        expiry_date = (
            self.expiry if self.expiry else timezone.now() + timedelta(days=365 * 100)
        )
        return expiry_date.isoformat()

    def __str__(self):
        return self.token