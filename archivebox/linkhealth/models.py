from typing import ClassVar

from django.db import models
from django.utils import timezone

from archivebox.uuid_compat import CompactUUIDField, uuid7


class LinkHealthSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    interval_days = models.PositiveSmallIntegerField(default=0)
    next_scan_at = models.DateTimeField(null=True, blank=True)


class LinkScan(models.Model):
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False)
    scope = models.CharField(max_length=16, default="all", editable=False)
    snapshot_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=16, default="queued", db_index=True)
    owner = models.ForeignKey("machine.Process", null=True, on_delete=models.SET_NULL)
    checked = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True)

    class Meta:
        ordering: ClassVar = ["-created_at"]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["scope"],
                condition=models.Q(status__in=["queued", "running"]),
                name="linkhealth_one_active_scan",
            ),
        ]


class LinkCheck(models.Model):
    class Status(models.TextChoices):
        OK = "ok", "Reachable"
        BROKEN = "broken", "Not found / gone"
        RESTRICTED = "restricted", "Restricted / rate limited"
        TEMPORARY = "temporary", "Server error"
        UNREACHABLE = "unreachable", "Connection failed"
        OTHER = "other", "Other response"
        UNSUPPORTED = "unsupported", "Not an HTTP URL"

    snapshot = models.OneToOneField("core.Snapshot", primary_key=True, on_delete=models.CASCADE, related_name="link_check")
    checked_at = models.DateTimeField(default=timezone.now)
    checked_url = models.TextField()
    normalized_url = models.TextField(db_index=True)
    status = models.CharField(max_length=16, choices=Status, db_index=True)
    status_code = models.PositiveSmallIntegerField(null=True)
    final_url = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    content_path = models.TextField(blank=True)
    message = models.TextField(blank=True)
