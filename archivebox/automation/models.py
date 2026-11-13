"""User-managed rules and an audit trail of their actual effects."""

from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from archivebox.uuid_compat import CompactUUIDField, uuid7


class Rule(models.Model):
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    TRIGGERS = [
        ("before_crawl", "Before a crawl is queued"),
        ("before_snapshot", "Before a page is captured"),
        ("capture", "A capture completes"),
        ("enrichment", "Automatic tags or summaries complete"),
        ("tag_added", "Tags are added"),
        ("tag_removed", "Tags are removed"),
        ("folder_moved", "A capture changes folder"),
    ]
    name = models.CharField(max_length=200)
    enabled = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    match = models.CharField(max_length=3, choices=[("all", "All conditions"), ("any", "Any condition")], default="all")
    trigger = models.CharField(max_length=20, choices=TRIGGERS, default="capture")
    groups = models.JSONField(default=dict, editable=False)
    add_tags = models.CharField(max_length=1000, blank=True, help_text="Comma-separated tags to add.")
    remove_tags = models.CharField(max_length=1000, blank=True, help_text="Comma-separated tags to remove.")
    permissions = models.CharField(
        max_length=16,
        blank=True,
        choices=[("", "Keep current visibility"), ("private", "Private"), ("unlisted", "Unlisted"), ("public", "Public")],
    )
    folder = models.ForeignKey(
        "core.Folder",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Move matching snapshots to this folder; leave blank to keep their folder.",
    )
    stop_processing = models.BooleanField(default=False, help_text="Stop later rules when this rule matches.")
    config_overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text="Capture settings as a JSON object. Values are checked against the installed configuration schemas.",
    )
    enable_plugins = models.JSONField(default=list, blank=True)
    disable_plugins = models.JSONField(default=list, blank=True)
    max_depth = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Before-crawl rules only. Leave blank to preserve the crawl's depth.",
    )

    class Meta:
        ordering: ClassVar = ["position", "pk"]

    def __str__(self):
        return self.name

    @property
    def is_capture_configuration(self):
        return self.trigger in ("before_crawl", "before_snapshot")

    @property
    def condition_summary(self):
        conditions = list(self.conditions.all())

        def describe(key, mode):
            parts = [
                f"{condition.get_field_display()} {condition.get_operator_display()} ‘{condition.value}’"
                for condition in conditions
                if condition.group == key
            ]
            parts += ["(" + describe(child, group["match"]) + ")" for child, group in self.groups.items() if group.get("parent", "") == key]
            return (" AND " if mode == "all" else " OR ").join(parts)

        return describe("", self.match)

    def clean(self):
        if not isinstance(self.groups, dict) or len(self.groups) > 20:
            raise ValidationError("Use at most 20 condition groups.")
        for key, group in self.groups.items():
            if (
                not isinstance(key, str)
                or not key
                or len(key) > 40
                or not isinstance(group, dict)
                or group.get("match") not in ("all", "any")
                or not isinstance(group.get("parent", ""), str)
            ):
                raise ValidationError("Each condition group must match all or any conditions.")
        for key, group in self.groups.items():
            seen = {key}
            parent = group.get("parent", "")
            while parent:
                if parent in seen or parent not in self.groups or len(seen) >= 6:
                    raise ValidationError("Condition groups must form a tree with no more than six levels.")
                seen.add(parent)
                parent = self.groups[parent].get("parent", "")
        # Use the same tag bounds as Snapshot/Tag instead of silently truncating.
        for field in ("add_tags", "remove_tags"):
            for tag in getattr(self, field).split(","):
                if len(tag.strip()) > 100:
                    raise ValidationError({field: "Each tag must be at most 100 characters."})
        from .capture import validate_capture_actions

        validate_capture_actions(self)
        if not any(
            (
                self.add_tags.strip(),
                self.remove_tags.strip(),
                self.permissions,
                self.folder_id,
                self.config_overrides,
                self.enable_plugins,
                self.disable_plugins,
                self.max_depth is not None,
            ),
        ):
            raise ValidationError("Choose at least one action.")


class RuleCondition(models.Model):
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    FIELD_CHOICES = [
        ("domain", "Domain"),
        ("url", "URL"),
        ("title", "Title"),
        ("tag", "Tag"),
        ("permissions", "Visibility"),
        ("event_tag", "Changed tag"),
        ("crawl_tag", "Crawl tag"),
        ("crawl_label", "Crawl label"),
    ]
    OPERATOR_CHOICES = [
        ("equals", "equals"),
        ("contains", "contains"),
        ("starts", "starts with"),
        ("not_equals", "does not equal"),
        ("not_contains", "does not contain"),
        ("in", "is one of (comma-separated)"),
        ("not_in", "is not one of (comma-separated)"),
    ]
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE, related_name="conditions")
    field = models.CharField(max_length=16, choices=FIELD_CHOICES, default="domain")
    operator = models.CharField(max_length=16, choices=OPERATOR_CHOICES, default="equals")
    value = models.CharField(max_length=1024)
    group = models.CharField(max_length=40, blank=True, default="")

    class Meta:
        ordering: ClassVar = ["pk"]


class RuleEvent(models.Model):
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    snapshot = models.ForeignKey("core.Snapshot", on_delete=models.CASCADE, related_name="automation_events")
    kind = models.CharField(max_length=20, choices=Rule.TRIGGERS)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, db_index=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["snapshot"], condition=models.Q(kind="capture"), name="automation_capture_event_once"),
            models.UniqueConstraint(fields=["snapshot"], condition=models.Q(kind="before_snapshot"), name="automation_prepare_event_once"),
        ]


class RuleRun(models.Model):
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    rule = models.ForeignKey(Rule, on_delete=models.SET_NULL, null=True)
    rule_name = models.CharField(max_length=200)
    snapshot = models.ForeignKey("core.Snapshot", on_delete=models.CASCADE, related_name="rule_runs", null=True)
    crawl = models.ForeignKey("crawls.Crawl", on_delete=models.CASCADE, related_name="rule_runs", null=True)
    phase = models.CharField(max_length=20, blank=True, default="", choices=Rule.TRIGGERS[:2])
    created_at = models.DateTimeField(default=timezone.now)
    automatic = models.BooleanField(default=True)
    matched = models.BooleanField(default=False)
    changes = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    event = models.ForeignKey(RuleEvent, null=True, on_delete=models.SET_NULL)

    class Meta:
        ordering: ClassVar = ["-created_at", "-pk"]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["rule", "event"],
                condition=models.Q(event__isnull=False),
                name="automation_once_per_rule_event",
            ),
        ]
