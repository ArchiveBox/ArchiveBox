import re
from typing import ClassVar

from django import forms
from django.core.validators import RegexValidator

from archivebox.crawls.schedule_util import validate_schedule
from archivebox.personas.models import Persona

from .models import ImporterSource


class ImporterSourceForm(forms.ModelForm):
    class Meta:
        model = ImporterSource
        fields = ("name", "persona", "limit", "tags", "schedule")
        help_texts: ClassVar = {
            "limit": "Items per batch (1–500). Import all continues until the source is exhausted.",
            "tags": "Comma-separated tags to apply to imported captures.",
            "schedule": "Leave blank for manual imports, or use hourly, daily, weekly, or a cron expression.",
        }

    def __init__(self, *args, definition, **kwargs):
        super().__init__(*args, **kwargs)
        self.definition = definition
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
        return data

    def save(self, commit=True):
        source = super().save(commit=False)
        source.plugin = self.definition.plugin
        source.feed = self.definition.feed
        source.settings = {key: self.cleaned_data[f"setting_{key}"] for key in self.definition.fields}
        if commit:
            source.save()
        return source
