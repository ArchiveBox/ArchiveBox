from typing import ClassVar

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from archivebox.uuid_compat import CompactUUIDField, uuid7


class ImporterQuerySet(models.QuerySet):
    def update(self, **kwargs):
        from archivebox.api.webhook_events import track_lifecycle_update, track_model_update

        with track_lifecycle_update(self, kwargs), track_model_update(self, kwargs):
            return super().update(**kwargs)


class ImporterSource(models.Model):
    objects = ImporterQuerySet.as_manager()

    emoji: str = "📥"
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    plugin = models.CharField(max_length=100)
    feed = models.CharField(max_length=100)
    persona = models.ForeignKey("personas.Persona", null=True, blank=True, on_delete=models.PROTECT)
    folder = models.ForeignKey("core.Folder", null=True, blank=True, on_delete=models.SET_NULL, related_name="importer_sources")
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

    def to_json(self):
        return {
            "type": "ImporterSource",
            "id": str(self.pk),
            "name": self.name,
            "plugin": self.plugin,
            "feed": self.feed,
            "created_by_id": self.created_by_id,
            "created_by_username": self.created_by.username,
            "created_at": self.created_at.isoformat(),
            "folder_id": str(self.folder_id) if self.folder_id else None,
            "folder_name": self.folder.name if self.folder_id else None,
            "persona_id": str(self.persona_id) if self.persona_id else None,
            "persona_name": self.persona.name if self.persona_id else None,
            "settings": self.settings,
            "checkpoint": self.checkpoint,
            "account": self.account,
            "limit": self.limit,
            "tags": self.tags,
            "schedule": self.schedule,
            "enabled": self.enabled,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
        }

    def get_absolute_url(self):
        return reverse("importers:detail", args=[self.pk])


class ImporterRun(models.Model):
    objects = ImporterQuerySet.as_manager()

    emoji: str = "🔄"

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
        RESET_CODE = "reset_code", "Reset learned code"

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

    def to_json(self):
        return {
            "type": "ImporterRun",
            "id": str(self.pk),
            "source_id": str(self.source_id),
            "source_name": self.source.name,
            "action": self.action,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "owner_id": str(self.owner_id) if self.owner_id else None,
            "crawl_id": str(self.crawl_id) if self.crawl_id else None,
            "cancel_requested": self.cancel_requested,
            "items": self.items,
            "result": self.result,
            "message": self.status_message,
        }

    @property
    def status_message(self):
        if self.message:
            return self.message
        if self.status == self.Status.QUEUED:
            return "Waiting for the ArchiveBox worker."
        if self.status == self.Status.RUNNING:
            return "Importer is running. No activity update yet."
        return self.get_status_display()

    class Meta:
        ordering: ClassVar = ["-created_at", "-id"]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["source"],
                condition=models.Q(status__in=["queued", "running"]),
                name="importers_one_active_run",
            ),
        ]
