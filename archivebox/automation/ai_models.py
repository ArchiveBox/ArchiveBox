from typing import ClassVar

from django.db import models
from django.utils import timezone


class AISettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False, help_text="Automatically summarize and tag future completed captures.")
    enabled_at = models.DateTimeField(default=timezone.now)
    model = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional provider/model, e.g. your configured Ollama model. Blank uses OpenCode's default.",
    )
    apply_tags = models.BooleanField(default=True, help_text="Add suggested tags without removing existing tags.")
    instructions = models.TextField(blank=True, max_length=4000, help_text="Optional summary language, length, or tagging preferences.")
    language = models.CharField(max_length=80, default="English", help_text="Language for generated summaries and topics.")
    tag_style = models.CharField(
        max_length=24,
        default="as_generated",
        choices=[
            ("as_generated", "No preference"),
            ("lower_spaces", "Lowercase · machine learning"),
            ("lower_hyphens", "Hyphenated · machine-learning"),
            ("lower_underscores", "Underscored · machine_learning"),
            ("title_spaces", "Title case · Machine Learning"),
            ("camel", "Camel case · machineLearning"),
        ],
    )
    allowed_tags = models.TextField(
        blank=True,
        max_length=5000,
        help_text="Optional curated topics, one per line. When set, AI can only use these exact names.",
    )


class Enrichment(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SUBMITTING = "submitting", "Starting OpenCode"
        RUNNING = "running", "Generating"
        SUCCEEDED = "succeeded", "Completed"
        FAILED = "failed", "Failed"

    snapshot = models.OneToOneField("core.Snapshot", on_delete=models.CASCADE, related_name="ai_enrichment")
    status = models.CharField(max_length=16, choices=Status, default=Status.QUEUED, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    session_id = models.CharField(max_length=200, blank=True)
    summary = models.TextField(blank=True)
    tags = models.JSONField(default=list)
    error = models.TextField(blank=True)
    model = models.CharField(max_length=200, blank=True)
    apply_tags = models.BooleanField(default=True)
    instructions = models.TextField(blank=True)
    preferences = models.JSONField(default=dict)

    class Meta:
        ordering: ClassVar = ["-created_at", "-pk"]
