from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone

from archivebox.uuid_compat import CompactUUIDField, uuid7


class StorageDestination(models.Model):
    class Provider(models.TextChoices):
        DRIVE = "drive", "Google Drive"
        S3 = "s3", "Amazon S3 / compatible storage"
        LOCAL = "local", "Local directory / mounted drive"

    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    name = models.CharField(max_length=150)
    provider = models.CharField(max_length=16, choices=Provider)
    path = models.CharField(max_length=2048)
    config_revision = models.CharField(max_length=32, blank=True, default="", editable=False)
    checked_at = models.DateTimeField(null=True)

    class Meta:
        ordering: ClassVar = ["name", "id"]

    def __str__(self):
        return self.name


class StorageRun(models.Model):
    class Action(models.TextChoices):
        INSTALL = "install", "Install rclone"
        CHECK = "check", "Check connection"
        COPY = "copy", "Copy sealed snapshots"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False)
    destination = models.ForeignKey(StorageDestination, related_name="runs", on_delete=models.PROTECT)
    destination_path = models.CharField(max_length=2048)
    config_revision = models.CharField(max_length=32, blank=True, default="", editable=False)
    action = models.CharField(max_length=16, choices=Action)
    status = models.CharField(max_length=16, choices=Status, default=Status.QUEUED, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    owner = models.ForeignKey("machine.Process", null=True, on_delete=models.SET_NULL)
    cancel_requested = models.BooleanField(default=False)
    copied_snapshots = models.PositiveIntegerField(default=0)
    total_snapshots = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True)

    class Meta:
        ordering: ClassVar = ["-created_at", "-id"]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["destination"],
                condition=models.Q(status__in=["queued", "running"]),
                name="storage_one_active_run",
            ),
        ]
