__package__ = 'archivebox.core'

import uuid

from django.db import models
from django.utils.functional import cached_property

from ..util import parse_date
from ..index.schema import Link


class Snapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    url = models.URLField(unique=True)
    timestamp = models.CharField(max_length=32, unique=True, db_index=True)

    title = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    tags = models.CharField(max_length=256, null=True, blank=True, db_index=True)

    added = models.DateTimeField(auto_now_add=True, db_index=True)
    updated = models.DateTimeField(null=True, blank=True, db_index=True)
    # bookmarked = models.DateTimeField()

    keys = ('url', 'timestamp', 'title', 'tags', 'updated')

    def __repr__(self) -> str:
        title = self.title or '-'
        return f'[{self.timestamp}] {self.url[:64]} ({title[:64]})'

    def __str__(self) -> str:
        title = self.title or '-'
        return f'[{self.timestamp}] {self.url[:64]} ({title[:64]})'

    @classmethod
    def from_json(cls, info: dict):
        info = {k: v for k, v in info.items() if k in cls.keys}
        return cls(**info)

    def as_json(self, *args) -> dict:
        args = args or self.keys
        return {
            key: getattr(self, key)
            for key in args
        }

    def as_link(self) -> Link:
        return Link.from_json(self.as_json())

    @cached_property
    def bookmarked(self):
        return parse_date(self.timestamp)

    @cached_property
    def is_archived(self):
        return self.as_link().is_archived

    @cached_property
    def num_outputs(self):
        return self.as_link().num_outputs

    @cached_property
    def url_hash(self):
        return self.as_link().url_hash

    @cached_property
    def base_url(self):
        return self.as_link().base_url

    @cached_property
    def link_dir(self):
        return self.as_link().link_dir

    @cached_property
    def archive_path(self):
        return self.as_link().archive_path

    @cached_property
    def archive_size(self):
        return self.as_link().archive_size

    @cached_property
    def history(self):
        from ..index import load_link_details
        return load_link_details(self.as_link()).history

    @cached_property
    def latest_title(self):
        if ('title' in self.history
            and self.history['title']
            and (self.history['title'][-1].status == 'succeeded')
            and self.history['title'][-1].output.strip()):
            return self.history['title'][-1].output.strip()
        return None
