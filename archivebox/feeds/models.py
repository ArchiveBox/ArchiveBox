import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse


class SavedFeed(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=200)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    filters = models.JSONField(default=dict)
    include_private = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)

    def get_absolute_url(self):
        return reverse("feeds:rss", args=[self.token])
