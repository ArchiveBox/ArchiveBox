from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from django.conf import settings
from django.db import IntegrityError, models
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.text import slugify

from archivebox.base_models.models import (
    ModelWithUUID,
    get_or_create_system_user_pk,
)
from archivebox.misc.util import (
    sanitize_html_text,
)

if TYPE_CHECKING:
    from .snapshots import Snapshot


class Tag(ModelWithUUID):
    # Keep AutoField for compatibility with main branch migrations
    # Don't use UUIDField here - requires complex FK transformation
    id = models.AutoField(primary_key=True, serialize=False, verbose_name="ID")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        default=get_or_create_system_user_pk,
        null=True,
        related_name="tag_set",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True, null=True)
    modified_at = models.DateTimeField(auto_now=True)
    name = models.CharField(unique=True, blank=False, max_length=100)

    @classmethod
    def get_or_create_by_name(
        cls,
        name: str,
        *,
        defaults: Mapping[str, Any] | None = None,
        created_by=None,
    ) -> tuple[Tag, bool]:
        name = cls.normalize_name(name)
        defaults = dict(defaults or {})
        if created_by is not None:
            defaults["created_by"] = created_by
        tag = cls.objects.filter(name__iexact=name).first()
        if tag:
            return tag, False
        try:
            return cls.objects.create(name=name, **(defaults or {})), True
        except IntegrityError:
            tag = cls.objects.filter(name__iexact=name).first()
            if tag is None:
                raise
            return tag, False

    @staticmethod
    def normalize_name(name: str) -> str:
        name = sanitize_html_text(name).strip()
        if not name:
            raise ValueError("Tag name is required")
        return name

    def rename(self, name: str) -> Tag:
        name = self.normalize_name(name)
        existing = type(self).objects.filter(name__iexact=name).exclude(pk=self.pk).first()
        if existing:
            raise ValueError(f'Tag "{existing.name}" already exists')
        if self.name != name:
            self.name = name
            self.save()
        return self

    snapshot_set: models.Manager[Snapshot]

    class Meta(ModelWithUUID.Meta):
        app_label = "core"
        verbose_name = "Tag"
        verbose_name_plural = "Tags"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is None or "name" in update_fields:
            self.name = sanitize_html_text(self.name).strip()
        super().save(*args, **kwargs)

    @property
    def slug(self) -> str:
        """ASCII-safe slugified form of the tag name (derived, not stored)."""
        return slugify(self.name or "") or "tag"

    @property
    def api_url(self) -> str:
        return str(reverse_lazy("api-1:get_tag", args=[self.id]))

    def to_json(self) -> dict:
        """
        Convert Tag model instance to a JSON-serializable dict.
        """
        from archivebox.config import VERSION

        return {
            "type": "Tag",
            "schema_version": VERSION,
            "id": str(self.id),
            "name": self.name,
        }

    @staticmethod
    def from_json(record: dict[str, Any], overrides: dict[str, Any] | None = None):
        """
        Create/update Tag from JSON dict.

        Args:
            record: JSON dict with 'name' field
            overrides: Optional dict with 'snapshot' to auto-attach tag

        Returns:
            Tag instance or None
        """
        name = record.get("name")
        if not name:
            return None

        tag, _ = Tag.get_or_create_by_name(name)

        # Auto-attach to snapshot if in overrides
        if overrides and "snapshot" in overrides and tag:
            overrides["snapshot"].add_tag_ids([tag.pk])

        return tag


class SnapshotTag(models.Model):
    id = models.AutoField(primary_key=True)
    snapshot = models.ForeignKey("Snapshot", db_column="snapshot_id", on_delete=models.CASCADE, to_field="id")
    tag = models.ForeignKey(Tag, db_column="tag_id", on_delete=models.CASCADE, to_field="id")

    class Meta:
        app_label = "core"
        db_table = "core_snapshot_tags"
        unique_together: ClassVar[list[tuple[str, str]]] = [("snapshot", "tag")]
