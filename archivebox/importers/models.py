from typing import ClassVar

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from archivebox.uuid_compat import CompactUUIDField, uuid7


class ImporterSource(models.Model):
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    plugin = models.CharField(max_length=100)
    feed = models.CharField(max_length=100)
    persona = models.ForeignKey("personas.Persona", null=True, blank=True, on_delete=models.PROTECT)
    settings = models.JSONField(default=dict)
    checkpoint = models.JSONField(default=dict)
    account = models.JSONField(default=dict)
    limit = models.PositiveIntegerField(default=100)
    tags = models.CharField(max_length=1024, blank=True)
    schedule = models.CharField(max_length=64, blank=True)
    enabled = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering: ClassVar = ["name", "id"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("importers:detail", args=[self.pk])


class ImporterRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        NEEDS_LOGIN = "needs_login", "Needs login"
        CANCELLED = "cancelled", "Cancelled"

    class Action(models.TextChoices):
        CHECK = "check", "Check access"
        PREVIEW = "preview", "Preview"
        IMPORT = "import", "Import"

    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False)
    source = models.ForeignKey(ImporterSource, related_name="runs", on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    action = models.CharField(max_length=16, choices=Action, default=Action.IMPORT)
    status = models.CharField(max_length=16, choices=Status, default=Status.QUEUED, db_index=True)
    cancel_requested = models.BooleanField(default=False)
    owner = models.ForeignKey("machine.Process", null=True, on_delete=models.SET_NULL)
    crawl = models.ForeignKey("crawls.Crawl", null=True, blank=True, on_delete=models.SET_NULL, related_name="import_runs")
    request = models.JSONField(default=dict)
    items = models.JSONField(default=list)
    result = models.JSONField(default=dict)
    message = models.TextField(blank=True)

    class Meta:
        ordering: ClassVar = ["-created_at", "-id"]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["source"],
                condition=models.Q(status__in=["queued", "running"]),
                name="importers_one_active_run",
            ),
        ]
