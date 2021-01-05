__package__ = 'archivebox.core'

import uuid

from django.db import models, transaction
from django.utils.functional import cached_property
from django.utils.text import slugify
from django.db.models import Case, When, Value, IntegerField

from ..util import parse_date
from ..index.schema import Link
from ..extractors import get_default_archive_methods, ARCHIVE_METHODS_INDEXING_PRECEDENCE

EXTRACTORS = [(extractor[0], extractor[0]) for extractor in get_default_archive_methods()]
STATUS_CHOICES = [
    ("succeeded", "succeeded"),
    ("failed", "failed"),
    ("skipped", "skipped")
]

try:
    JSONField = models.JSONField
except AttributeError:
    import jsonfield
    JSONField = jsonfield.JSONField


class Tag(models.Model):
    """
    Based on django-taggit model
    """
    name = models.CharField(verbose_name="name", unique=True, blank=False, max_length=100)
    slug = models.SlugField(verbose_name="slug", unique=True, max_length=100)

    class Meta:
        verbose_name = "Tag"
        verbose_name_plural = "Tags"

    def __str__(self):
        return self.name

    def slugify(self, tag, i=None):
        slug = slugify(tag)
        if i is not None:
            slug += "_%d" % i
        return slug

    def save(self, *args, **kwargs):
        if self._state.adding and not self.slug:
            self.slug = self.slugify(self.name)

            with transaction.atomic():
                slugs = set(
                    type(self)
                    ._default_manager.filter(slug__startswith=self.slug)
                    .values_list("slug", flat=True)
                )

                i = None
                while True:
                    slug = self.slugify(self.name, i)
                    if slug not in slugs:
                        self.slug = slug
                        return super().save(*args, **kwargs)
                    i = 1 if i is None else i+1
        else:
            return super().save(*args, **kwargs)


class Snapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    url = models.URLField(unique=True)
    timestamp = models.CharField(max_length=32, unique=True, db_index=True)

    title = models.CharField(max_length=128, null=True, blank=True, db_index=True)

    added = models.DateTimeField(auto_now_add=True, db_index=True)
    updated = models.DateTimeField(null=True, blank=True, db_index=True)
    tags = models.ManyToManyField(Tag)

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
            if key != 'tags' else self.tags_str()
            for key in args
        }

    def as_link(self) -> Link:
        return Link.from_json(self.as_json())

    def as_link_with_details(self) -> Link:
        from ..index import load_link_details
        return load_link_details(self.as_link())

    def tags_str(self) -> str:
        return ','.join(self.tags.order_by('name').values_list('name', flat=True))

    @cached_property
    def bookmarked(self):
        return parse_date(self.timestamp)

    @cached_property
    def is_archived(self):
        return self.as_link().is_archived

    @cached_property
    def num_outputs(self):
        return self.archiveresult_set.filter(status='succeeded').count()

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
        # TODO: use ArchiveResult for this instead of json
        return self.as_link_with_details().history

    @cached_property
    def latest_title(self):
        if ('title' in self.history
            and self.history['title']
            and (self.history['title'][-1].status == 'succeeded')
            and self.history['title'][-1].output.strip()):
            return self.history['title'][-1].output.strip()
        return None

    def save_tags(self, tags=()):
        tags_id = []
        for tag in tags:
            tags_id.append(Tag.objects.get_or_create(name=tag)[0].id)
        self.tags.clear()
        self.tags.add(*tags_id)


class ArchiveResultManager(models.Manager):
    def indexable(self, sorted: bool = True):
        INDEXABLE_METHODS = [ r[0] for r in ARCHIVE_METHODS_INDEXING_PRECEDENCE ]
        qs = self.get_queryset().filter(extractor__in=INDEXABLE_METHODS,status='succeeded')

        if sorted:
            precedence = [ When(extractor=method, then=Value(precedence)) for method, precedence in ARCHIVE_METHODS_INDEXING_PRECEDENCE ]
            qs = qs.annotate(indexing_precedence=Case(*precedence, default=Value(1000),output_field=IntegerField())).order_by('indexing_precedence')
        return qs


class ArchiveResult(models.Model):
    snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE)
    cmd = JSONField()
    pwd = models.CharField(max_length=256)
    cmd_version = models.CharField(max_length=32, default=None, null=True, blank=True)
    output = models.CharField(max_length=512)
    start_ts = models.DateTimeField()
    end_ts = models.DateTimeField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    extractor = models.CharField(choices=EXTRACTORS, max_length=32)

    objects = ArchiveResultManager()

    def __str__(self):
        return self.extractor
