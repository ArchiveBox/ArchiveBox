import re
from copy import deepcopy
from typing import ClassVar

from django import forms
from django.core.validators import RegexValidator
from django.utils import timezone

from archivebox.crawls.schedule_util import next_run_for_schedule, validate_schedule
from archivebox.personas.models import Persona

from .models import ImporterSource


class ImporterSourceForm(forms.ModelForm):
    class Meta:
        model = ImporterSource
        fields = ("name", "persona", "folder", "limit", "tags", "schedule")
        help_texts: ClassVar = {
            "limit": "Items per batch (1–500). Import all continues until the source is exhausted.",
            "tags": "Comma-separated tags to apply to imported captures.",
            "schedule": "Leave blank for manual imports, or use hourly, daily, weekly, or a cron expression.",
        }

    def __init__(self, *args, definition, **kwargs):
        super().__init__(*args, **kwargs)
        self.definition = definition
        self._original_settings = deepcopy(self.instance.settings)
        self._original_persona_id = self.instance.persona_id
        self._original_checkpoint = deepcopy(self.instance.checkpoint)
        self._original_enabled = self.instance.enabled
        self.fields["name"].required = False
        self.fields["name"].initial = self.instance.name or f"{definition.provider} · {definition.title}"
        self.fields["persona"].queryset = Persona.objects.order_by("name")
        self.fields["persona"].required = definition.auth == "persona"
        self.fields["persona"].help_text = "Authentication and capture settings from this server persona."
        self.fields["limit"] = forms.IntegerField(
            min_value=1,
            max_value=500,
            initial=100,
            required=False,
            help_text=self._meta.help_texts["limit"],
        )
        self.fields["schedule"].widget.attrs["placeholder"] = "e.g. daily"
        for key, schema in definition.fields.items():
            options = {
                "label": schema.get("title") or key.replace("_", " ").title(),
                "help_text": schema.get("description", ""),
                "initial": (self.instance.settings or {}).get(key, schema.get("default", "")),
                "required": bool(schema.get("x-required", False)),
            }
            kind = schema.get("type", "string")
            if kind == "integer":
                field = forms.IntegerField(min_value=schema.get("minimum"), max_value=schema.get("maximum"), **options)
            elif kind == "boolean":
                field = forms.BooleanField(**{**options, "required": False})
            elif schema.get("enum"):
                field = forms.ChoiceField(choices=[(value, value) for value in schema["enum"]], **options)
            elif kind in {"array", "object"}:
                field = forms.JSONField(**options)
            elif schema.get("format") == "uri":
                field = forms.URLField(max_length=4096, assume_scheme="https", **options)
            else:
                validators = [RegexValidator(re.compile(schema["pattern"]))] if schema.get("pattern") else []
                field = forms.CharField(max_length=schema.get("maxLength", 4096), validators=validators, **options)
            self.fields[f"setting_{key}"] = field

    @property
    def basic_fields(self):
        return [self[key] for key in self.fields if key not in self.advanced_names]

    @property
    def advanced_names(self):
        return {
            "name",
            "folder",
            "limit",
            "tags",
            "schedule",
            *({"persona"} if self.definition.auth != "persona" else set()),
            *(f"setting_{key}" for key, schema in self.definition.fields.items() if schema.get("x-advanced")),
        }

    @property
    def advanced_fields(self):
        return [self[key] for key in self.fields if key in self.advanced_names]

    @property
    def advanced_errors(self):
        return any(field.errors for field in self.advanced_fields)

    def clean_folder(self):
        folder = self.cleaned_data["folder"]
        if folder and folder.is_smart and not folder.is_container:
            raise forms.ValidationError("Choose a regular folder as the destination.")
        return folder

    def clean_name(self):
        return self.cleaned_data["name"].strip() or f"{self.definition.provider} · {self.definition.title}"

    def clean_limit(self):
        return self.cleaned_data["limit"] or 100

    def clean_schedule(self):
        value = self.cleaned_data["schedule"].strip()
        try:
            return validate_schedule(value) if value else ""
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error

    def clean(self):
        data = super().clean()
        for key, schema in self.definition.fields.items():
            value = data.get(f"setting_{key}")
            if schema.get("type") in {"array", "object"} and value is not None:
                expected = list if schema["type"] == "array" else dict
                if not isinstance(value, expected):
                    self.add_error(f"setting_{key}", f"Expected a JSON {schema['type']}.")
        settings = {key: data.get(f"setting_{key}") for key in self.definition.fields}
        persona = data.get("persona")
        if (
            not self.errors
            and self._original_checkpoint
            and (settings != self._original_settings or (persona.pk if persona else None) != self._original_persona_id)
        ):
            self.add_error(None, "Reset progress on the importer before changing its source settings or persona.")
        return data

    def save(self, commit=True, *, enabled=None):
        source = super().save(commit=False)
        source.plugin = self.definition.plugin
        source.feed = self.definition.feed
        source.settings = {key: self.cleaned_data[f"setting_{key}"] for key in self.definition.fields}
        if enabled is not None:
            if type(enabled) is not bool:
                raise ValueError("Enabled must be a boolean.")
            source.enabled = enabled
        if commit:
            from .service import ACTIVE_STATUSES

            source.next_run_at = next_run_for_schedule(source.schedule, timezone.now()) if source.schedule and source.enabled else None
            if source._state.adding:
                source.save()
            else:
                saved = (
                    ImporterSource.objects.filter(pk=source.pk, checkpoint=self._original_checkpoint, enabled=self._original_enabled)
                    .exclude(runs__status__in=ACTIVE_STATUSES)
                    .update(**{key: getattr(source, key) for key in (*self._meta.fields, "settings", "enabled", "next_run_at")})
                )
                if not saved:
                    raise ValueError("The importer is active or its progress or schedule changed. Pause it and reload before editing.")
            source.refresh_from_db()
        return source
