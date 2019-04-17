__package__ = 'archivebox.core'

import uuid

from django.db import models


class Page(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    url = models.URLField(unique=True)
    timestamp = models.CharField(unique=True, max_length=32, null=True, default=None)

    title = models.CharField(max_length=128, null=True, default=None)
    tags = models.CharField(max_length=256, null=True, default=None)

    added = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(null=True, default=None)
    # bookmarked = models.DateTimeField()

    sql_args = ('url', 'timestamp', 'title', 'tags', 'updated')

    @classmethod
    def from_json(cls, info: dict):
        info = {k: v for k, v in info.items() if k in cls.sql_args}
        return cls(**info)

    def as_json(self, *args) -> dict:
        args = args or self.sql_args
        return {
            key: getattr(self, key)
            for key in args
        }
