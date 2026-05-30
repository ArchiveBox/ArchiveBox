__package__ = "archivebox.core"

import json
import re
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
from typing import Any

from django import forms
from django.utils.html import format_html

from archivebox.misc.util import URL_REGEX, find_all_urls, parse_filesize_to_bytes
from taggit.utils import edit_string_for_tags, parse_tags
from archivebox.base_models.admin import KeyValueWidget
from archivebox.crawls.schedule_utils import validate_schedule
from archivebox.config.common import get_config, parse_delete_after
from archivebox.core.permissions import (
    PERMISSIONS_CHOICES,
    PERMISSIONS_PUBLIC,
    PERMISSIONS_UNLISTED,
    filter_personas_by_permissions,
    is_admin_user,
)
from archivebox.core.widgets import TagEditorWidget, URLFiltersWidget
from archivebox.hooks import get_plugins, discover_plugin_configs, get_plugin_icon
from archivebox.personas.models import Persona

DEPTH_CHOICES = (
    ("0", "depth = 0 (archive just these URLs)"),
    ("1", "depth = 1 (+ URLs one hop away)"),
    ("2", "depth = 2 (+ URLs two hops away)"),
    ("3", "depth = 3 (+ URLs three hops away)"),
    ("4", "depth = 4 (+ URLs four hops away)"),
)

PLUGIN_CONFIG_FIELD_PREFIX = "plugin_config__"
PLUGIN_GROUP_DEFINITIONS = (
    (
        "main_plugins",
        "Main",
        "",
        "",
        "",
        (
            "dom",
            "screenshot",
            "pdf",
            "singlefile",
            "wget",
            "archivedotorg",
            "chrome_mhtml",
        ),
    ),
    (
        "page_setup_plugins",
        "Page Setup",
        "",
        "",
        "",
        (
            "chrome",
            "infiniscroll",
            "modalcloser",
            "ublock",
            "istilldontcareaboutcookies",
            "twocaptcha",
            "claudechrome",
        ),
    ),
    (
        "media_plugins",
        "Media",
        "",
        "",
        "",
        (
            "staticfile",
            "responses",
            "chrome_screencast",
            "ytdlp",
            "gallerydl",
            "git",
        ),
    ),
    (
        "text_plugins",
        "Text",
        "",
        "",
        "",
        (
            "readability",
            "htmltotext",
            "defuddle",
            "forumdl",
            "mercury",
            "trafilatura",
            "liteparse",
            "opendataloader",
            "papersdl",
        ),
    ),
    (
        "metadata_plugins",
        "Metadata",
        "",
        "",
        "",
        (
            "title",
            "favicon",
            "headers",
            "redirects",
            "accessibility",
            "consolelog",
            "sslcerts",
            "dns",
            "seo",
            "hashes",
        ),
    ),
    (
        "postprocessing_plugins",
        "Postprocessing",
        "",
        "",
        "",
        (
            "parse_dom_outlinks",
            "parse_html_urls",
            "parse_jsonl_urls",
            "parse_netscape_urls",
            "parse_rss_urls",
            "parse_txt_urls",
            "claudecode",
            "claudecodecleanup",
            "claudecodeextract",
        ),
    ),
)
HIDDEN_PLUGIN_CONFIG_UI_PLUGINS = {
    "apt",
    "base",
    "bash",
    "brew",
    "cargo",
    "chromewebstore",
    "env",
    "media",
    "npm",
    "pip",
    "puppeteer",
    "search_backend_ripgrep",
    "search_backend_sonic",
    "search_backend_sqlite",
    "ssl",
}
TIMEOUT_INPUT_PATTERN = r"(0|[1-9][0-9]*|[0-9]+(?:\.[0-9]+)?\s*(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours))"


def get_plugin_choices():
    """Get available extractor plugins from discovered hooks."""
    return [(name, name) for name in get_plugins()]


def get_plugin_choice_label(plugin_name: str, plugin_configs: dict[str, dict]) -> str:
    schema = plugin_configs.get(plugin_name, {})
    description = str(schema.get("description") or "").strip()
    if not description:
        return plugin_name
    icon_html = get_plugin_icon(plugin_name)

    return format_html(
        '<span class="plugin-choice-icon">{}</span><span class="plugin-choice-name">{}</span><a class="plugin-choice-description" href="https://archivebox.github.io/abx-plugins/#{}" target="_blank" rel="noopener noreferrer">{}</a>',
        icon_html,
        plugin_name,
        plugin_name,
        description,
    )


def get_choice_field(form: forms.Form, name: str) -> forms.ChoiceField:
    field = form.fields[name]
    if not isinstance(field, forms.ChoiceField):
        raise TypeError(f"{name} must be a ChoiceField")
    return field


def _plugin_config_input_name(plugin_name: str, config_key: str) -> str:
    return f"{PLUGIN_CONFIG_FIELD_PREFIX}{plugin_name}__{config_key}"


def _schema_types(schema: Mapping[str, Any]) -> list[str]:
    raw_type = schema.get("type") or "string"
    if isinstance(raw_type, list):
        return [str(item) for item in raw_type]
    return [str(raw_type)]


def _jsonish(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _same_config_value(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, default=str) == json.dumps(right, sort_keys=True, default=str)


def _coerce_plugin_config_value(raw_value: Any, schema: Mapping[str, Any]) -> Any:
    schema_types = _schema_types(schema)

    if "boolean" in schema_types:
        if isinstance(raw_value, bool):
            return raw_value
        value = str(raw_value).strip().lower()
        if value in {"true", "1", "yes", "on"}:
            return True
        if value in {"false", "0", "no", "off", ""}:
            return False
        raise forms.ValidationError("Must be true or false.")

    if "integer" in schema_types:
        value = int(str(raw_value).strip())
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < int(minimum):
            raise forms.ValidationError(f"Must be at least {minimum}.")
        if maximum is not None and value > int(maximum):
            raise forms.ValidationError(f"Must be at most {maximum}.")
        return value

    if "number" in schema_types:
        value = float(str(raw_value).strip())
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < float(minimum):
            raise forms.ValidationError(f"Must be at least {minimum}.")
        if maximum is not None and value > float(maximum):
            raise forms.ValidationError(f"Must be at most {maximum}.")
        return value

    if "array" in schema_types:
        if isinstance(raw_value, list):
            return raw_value
        value = str(raw_value).strip()
        if not value:
            return []
        if value.startswith("["):
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                raise forms.ValidationError("Must be a JSON array.")
            return parsed
        return [item.strip() for item in value.replace(",", "\n").splitlines() if item.strip()]

    if "object" in schema_types:
        value = str(raw_value).strip()
        if not value:
            return {}
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise forms.ValidationError("Must be a JSON object.")
        return parsed

    value = str(raw_value)
    enum = schema.get("enum")
    if isinstance(enum, list) and enum and value not in {str(item) for item in enum}:
        raise forms.ValidationError(f"Must be one of: {', '.join(str(item) for item in enum)}.")
    return value


class PluginConfigFormMixin:
    plugin_groups: list[dict[str, Any]]

    def build_plugin_groups(self, runtime_config: Mapping[str, Any] | None = None) -> None:
        all_plugins = get_plugins()
        plugin_configs = discover_plugin_configs()
        runtime_config = runtime_config or get_config()
        self.plugin_config_binary_urls = get_plugin_config_binary_urls(runtime_config)
        grouped_plugins = set().union(*(group[-1] for group in PLUGIN_GROUP_DEFINITIONS))
        other_plugins = tuple(sorted(set(all_plugins) - grouped_plugins - HIDDEN_PLUGIN_CONFIG_UI_PLUGINS))

        for field_name, *_rest, plugin_names in PLUGIN_GROUP_DEFINITIONS:
            if field_name in self.fields:
                get_choice_field(self, field_name).choices = [
                    (p, get_plugin_choice_label(p, plugin_configs)) for p in plugin_names if p in all_plugins
                ]

        if "other_plugins" in self.fields:
            get_choice_field(self, "other_plugins").choices = [(p, get_plugin_choice_label(p, plugin_configs)) for p in other_plugins]

        group_specs = (
            *PLUGIN_GROUP_DEFINITIONS,
            ("other_plugins", "Other", "", "", "", other_plugins),
        )
        self.plugin_groups = [
            {
                "field_name": field_name,
                "title": title,
                "note": note,
                "dom_id": dom_id,
                "select_all_group": select_all_group,
                "show_selectors": field_name in self.fields,
                "plugins": self._build_plugin_cards(field_name, plugin_names, plugin_configs, runtime_config),
            }
            for field_name, title, note, dom_id, select_all_group, plugin_names in group_specs
            if any(plugin in all_plugins for plugin in plugin_names)
        ]

    def _build_plugin_cards(
        self,
        field_name: str,
        plugin_names: Iterable[str],
        plugin_configs: dict[str, dict[str, Any]],
        runtime_config: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        if field_name in self.fields:
            choices = list(get_choice_field(self, field_name).choices)
            selected_values = set(self.data.getlist(field_name)) if self.is_bound else set(get_choice_field(self, field_name).initial or [])
        else:
            all_plugins = get_plugins()
            choices = [(p, get_plugin_choice_label(p, plugin_configs)) for p in plugin_names if p in all_plugins]
            selected_values = set()

        cards = []
        for index, (plugin_name, label) in enumerate(choices):
            schema = plugin_configs.get(str(plugin_name), {})
            properties = schema.get("properties") or {}
            enabled_config_key = f"{str(plugin_name).upper()}_ENABLED"
            enabled_prop_schema = properties.get(enabled_config_key)
            if not isinstance(enabled_prop_schema, dict) or "boolean" not in _schema_types(enabled_prop_schema):
                enabled_config_key = ""
            config_fields = [
                self._build_plugin_config_field(str(plugin_name), str(config_key), prop_schema, runtime_config)
                for config_key, prop_schema in properties.items()
                if isinstance(prop_schema, dict)
            ]
            cards.append(
                {
                    "name": str(plugin_name),
                    "label": label,
                    "checked": str(plugin_name) in selected_values,
                    "checkbox_id": f"id_{field_name}_{index}",
                    "enabled_config_key": enabled_config_key,
                    "description": str(schema.get("description") or "").strip(),
                    "source_url": f"https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/{plugin_name}",
                    "docs_url": f"https://archivebox.github.io/abx-plugins/#{plugin_name}",
                    "required_plugins": [str(item) for item in schema.get("required_plugins") or []],
                    "required_binaries_count": len(schema.get("required_binaries") or []),
                    "config_fields": config_fields,
                    "config_count": len(config_fields),
                },
            )
        return cards

    def _build_plugin_config_field(
        self,
        plugin_name: str,
        config_key: str,
        prop_schema: Mapping[str, Any],
        runtime_config: Mapping[str, Any],
    ) -> dict[str, Any]:
        schema_types = _schema_types(prop_schema)
        enum = prop_schema.get("enum")
        input_name = _plugin_config_input_name(plugin_name, config_key)
        current_value = runtime_config.get(config_key, prop_schema.get("default", ""))
        if self.is_bound and input_name in self.data:
            try:
                current_value = _coerce_plugin_config_value(self.data.get(input_name), prop_schema)
            except (TypeError, ValueError, json.JSONDecodeError, forms.ValidationError):
                current_value = self.data.get(input_name)

        default_value = prop_schema.get("default", "")
        fallback_key = prop_schema.get("x-fallback")
        default_display = f"{{{fallback_key}}}" if fallback_key else default_value
        is_sensitive = bool(prop_schema.get("x-sensitive"))
        input_value = "" if is_sensitive else _jsonish(current_value)
        field_kind = "text"
        input_type = "text"
        options = []

        if "boolean" in schema_types:
            field_kind = "boolean"
            input_value = "true" if bool(current_value) else "false"
        elif isinstance(enum, list) and enum:
            field_kind = "select"
            options = [
                {
                    "value": str(option),
                    "label": str(option),
                    "selected": str(option) == str(current_value),
                }
                for option in enum
            ]
        elif "integer" in schema_types or "number" in schema_types:
            field_kind = "number"
            input_type = "number"
        elif "array" in schema_types or "object" in schema_types:
            field_kind = "json"
            input_value = "" if is_sensitive else json.dumps(current_value, indent=2, sort_keys=True, default=str)
        elif is_sensitive:
            input_type = "password"

        return {
            "key": config_key,
            "input_name": input_name,
            "kind": field_kind,
            "input_type": input_type,
            "value": input_value,
            "checked": bool(current_value),
            "options": options,
            "description": str(prop_schema.get("description") or "").strip(),
            "default": _jsonish(default_display),
            "current": "configured" if is_sensitive and current_value else _jsonish(current_value),
            "current_url": self.plugin_config_binary_urls.get(config_key, "") if str(config_key).endswith("_BINARY") else "",
            "is_sensitive": is_sensitive,
            "minimum": prop_schema.get("minimum"),
            "maximum": prop_schema.get("maximum"),
            "pattern": prop_schema.get("pattern"),
            "type_label": " / ".join(schema_types),
        }

    def clean_plugin_config_overrides(self, effective_config: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not self.is_bound:
            return {}

        effective_config = effective_config or get_config()
        overrides: dict[str, Any] = {}
        sources: dict[str, str] = {}

        for plugin_name, schema in discover_plugin_configs().items():
            for config_key, prop_schema in (schema.get("properties") or {}).items():
                if not isinstance(prop_schema, dict):
                    continue

                input_name = _plugin_config_input_name(plugin_name, config_key)
                if input_name not in self.data:
                    continue

                raw_value: Any = self.data.get(input_name)
                if "array" in _schema_types(prop_schema) and isinstance(prop_schema.get("enum"), list):
                    raw_value = self.data.getlist(input_name)

                if prop_schema.get("x-sensitive") and raw_value == "":
                    continue

                try:
                    coerced_value = _coerce_plugin_config_value(raw_value, prop_schema)
                except (TypeError, ValueError, json.JSONDecodeError) as err:
                    self.add_error("config", forms.ValidationError(f"{config_key}: {err}"))
                    continue
                except forms.ValidationError as err:
                    self.add_error("config", forms.ValidationError(f"{config_key}: {err.messages[0]}"))
                    continue

                base_value = effective_config.get(config_key, prop_schema.get("default", ""))
                if _same_config_value(coerced_value, base_value):
                    continue

                existing_value = overrides.get(config_key)
                if config_key in overrides and not _same_config_value(existing_value, coerced_value):
                    self.add_error(
                        "config",
                        forms.ValidationError(
                            f"{config_key} was set differently under {sources[config_key]} and {plugin_name}. Set it once in Custom config overrides.",
                        ),
                    )
                    continue

                overrides[config_key] = coerced_value
                sources[config_key] = plugin_name

        return overrides

    def plugin_config_keys(self) -> set[str]:
        return {
            str(config_key)
            for schema in discover_plugin_configs().values()
            for config_key, prop_schema in (schema.get("properties") or {}).items()
            if isinstance(prop_schema, dict)
        }


def get_plugin_config_binary_urls(runtime_config: Mapping[str, Any]) -> dict[str, str]:
    from archivebox.config.views import get_environment_binary_url, get_installed_binary_change_url
    from archivebox.machine.models import Binary, Machine

    binary_keys = {
        str(config_key)
        for schema in discover_plugin_configs().values()
        for config_key, prop_schema in (schema.get("properties") or {}).items()
        if isinstance(prop_schema, dict) and str(config_key).endswith("_BINARY")
    }
    urls: dict[str, str] = {}
    machine = Machine.current()
    for key in binary_keys:
        value = str(runtime_config.get(key) or "").strip()
        if not value:
            continue
        name = Path(value).name if "/" in value else value
        binary = Binary.objects.get_valid_binary(value, machine=machine)
        if binary is None and "/" in value:
            binary = (
                Binary.objects.exclude(abspath="")
                .exclude(abspath__isnull=True)
                .filter(machine=machine, abspath=value)
                .order_by("-modified_at")
                .first()
            )
        if binary is None and name != value:
            binary = Binary.objects.get_valid_binary(name, machine=machine)
        urls[key] = get_installed_binary_change_url(getattr(binary, "name", name), binary) or get_environment_binary_url(name)
    return urls


class AddLinkForm(PluginConfigFormMixin, forms.Form):
    # Basic fields
    url = forms.CharField(
        label="URLs",
        strip=True,
        widget=forms.Textarea(
            attrs={
                "data-url-regex": URL_REGEX.pattern,
                "placeholder": (
                    "Enter URLs to archive, as one per line, CSV, JSON, or embedded in text "
                    "(e.g. markdown, HTML, etc.). Examples:\n"
                    "https://example.com\n"
                    "https://news.ycombinator.com,https://news.google.com\n"
                    "[ArchiveBox](https://github.com/ArchiveBox/ArchiveBox)"
                ),
            },
        ),
        required=True,
    )
    tag = forms.CharField(
        label="Tags",
        strip=True,
        required=False,
        widget=TagEditorWidget(),
    )
    depth = forms.ChoiceField(
        label="Archive depth",
        choices=DEPTH_CHOICES,
        initial="0",
        widget=forms.RadioSelect(attrs={"class": "depth-selection"}),
    )
    max_urls = forms.IntegerField(
        label="Max crawl URLs",
        required=False,
        min_value=0,
        initial=0,
        widget=forms.NumberInput(
            attrs={
                "min": 0,
                "step": 1,
                "placeholder": "0 = unlimited",
            },
        ),
    )
    crawl_max_size = forms.CharField(
        label="Max crawl size",
        required=False,
        initial="0",
        widget=forms.TextInput(
            attrs={
                "placeholder": "0 = unlimited, or e.g. 45mb / 1gb",
            },
        ),
    )
    crawl_timeout = forms.CharField(
        label="Max crawl time",
        required=False,
        initial=0,
        widget=forms.TextInput(
            attrs={
                "pattern": TIMEOUT_INPUT_PATTERN,
                "title": "Use 0, integer seconds, or a duration like 1.5m or 1hr. Non-zero values must be greater than 10 seconds.",
                "placeholder": "0, 300, 1.5m, or 1hr",
            },
        ),
    )
    timeout = forms.CharField(
        label="Max subtask time",
        required=False,
        widget=forms.TextInput(
            attrs={
                "pattern": TIMEOUT_INPUT_PATTERN,
                "title": "Use integer seconds or a duration like 1.5m or 1hr. Non-zero values must be greater than 10 seconds.",
                "placeholder": "60, 1.5m, or 1hr",
            },
        ),
    )
    snapshot_max_size = forms.CharField(
        label="Max snapshot size",
        required=False,
        initial="0",
        widget=forms.TextInput(
            attrs={
                "placeholder": "0 = unlimited, or e.g. 45mb / 1gb",
            },
        ),
    )
    delete_after = forms.CharField(
        label="Delete after",
        required=False,
        initial="0",
        widget=forms.TextInput(
            attrs={
                "placeholder": "0 = keep forever, or e.g. 1d / 6mo",
            },
        ),
    )
    crawl_max_concurrent_snapshots = forms.IntegerField(
        label="Max in parallel",
        required=False,
        min_value=1,
        widget=forms.NumberInput(
            attrs={
                "min": 1,
                "step": 1,
            },
        ),
    )
    notes = forms.CharField(
        label="Notes",
        strip=True,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Optional notes about this crawl",
            },
        ),
    )
    url_filters = forms.Field(
        label="URL allowlist / denylist",
        required=False,
        widget=URLFiltersWidget(source_selector='textarea[name="url"]'),
    )

    # Plugin groups
    main_plugins = forms.MultipleChoiceField(
        label="Main",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],  # populated in __init__
    )
    page_setup_plugins = forms.MultipleChoiceField(
        label="Page Setup",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    media_plugins = forms.MultipleChoiceField(
        label="Media",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    text_plugins = forms.MultipleChoiceField(
        label="Text",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    metadata_plugins = forms.MultipleChoiceField(
        label="Metadata",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    postprocessing_plugins = forms.MultipleChoiceField(
        label="Postprocessing",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )
    other_plugins = forms.MultipleChoiceField(
        label="Other",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=[],
    )

    # Advanced options
    schedule = forms.CharField(
        label="Repeat schedule",
        max_length=64,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g., daily, weekly, 0 */6 * * * (every 6 hours)",
            },
        ),
    )
    persona = forms.ModelChoiceField(
        label="Persona (configuration profile)",
        required=False,
        queryset=Persona.objects.none(),
        empty_label=None,
        to_field_name="name",
    )
    permissions = forms.ChoiceField(
        label="Permissions",
        choices=PERMISSIONS_CHOICES,
        initial="public",
        required=True,
    )
    start_paused = forms.BooleanField(
        label="Start paused",
        initial=False,
        required=False,
    )
    config = forms.JSONField(
        label="Custom config overrides",
        widget=KeyValueWidget(),
        initial=dict,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        self.can_override_crawl_config = bool(self.request and is_admin_user(self.request))
        self.is_authenticated_user = bool(self.request and self.request.user.is_authenticated)
        super().__init__(*args, **kwargs)

        default_persona = Persona.get_or_create_default()
        persona_queryset = Persona.objects.order_by("name")
        if not self.can_override_crawl_config:
            persona_queryset = filter_personas_by_permissions(persona_queryset, {PERMISSIONS_PUBLIC})
        self.fields["persona"].queryset = persona_queryset

        selected_persona = persona_queryset.filter(id=default_persona.id).first() or persona_queryset.first()
        default_config = get_config(persona=selected_persona) if selected_persona else get_config()
        if selected_persona:
            self.fields["persona"].initial = selected_persona.name
        self.fields["permissions"].initial = default_config.PERMISSIONS
        if not self.can_override_crawl_config:
            # Non-staff users may only mark their own crawl public/unlisted (never private),
            # and anonymous users have no say at all (forced public, see clean()).
            self.fields["permissions"].choices = [
                (PERMISSIONS_PUBLIC, "Public"),
                (PERMISSIONS_UNLISTED, "Unlisted"),
            ]
            self.fields["permissions"].required = self.is_authenticated_user
            if str(self.fields["permissions"].initial or "").strip().lower() not in {PERMISSIONS_PUBLIC, PERMISSIONS_UNLISTED}:
                self.fields["permissions"].initial = PERMISSIONS_PUBLIC
        self.fields["timeout"].initial = default_config.TIMEOUT
        self.fields["crawl_max_concurrent_snapshots"].initial = default_config.CRAWL_MAX_CONCURRENT_SNAPSHOTS
        self.fields["delete_after"].initial = default_config.DELETE_AFTER
        self.fields["url_filters"].initial = {
            "allowlist": "",
            "denylist": "",
            "same_domain_only": False,
            "subpaths_only": False,
            "only_new": bool(default_config.ONLY_NEW),
        }

        if self.is_bound:
            selected_persona = (
                persona_queryset.filter(name=str(self.data.get(self.add_prefix("persona")) or "")).first() or selected_persona
            )
        if self.can_override_crawl_config:
            self.build_plugin_groups(get_config(persona=selected_persona) if selected_persona else get_config())
        else:
            all_plugins = get_plugins()
            for field_name, *_rest, plugin_names in PLUGIN_GROUP_DEFINITIONS:
                get_choice_field(self, field_name).choices = [(p, p) for p in all_plugins if p in plugin_names]
            get_choice_field(self, "other_plugins").choices = [(p, p) for p in all_plugins]
            self.plugin_groups = []

    def clean(self):
        cleaned_data = super().clean() or {}

        if not self.can_override_crawl_config:
            # Non-staff users cannot set any crawl config (plugins, plugin_config, custom
            # KEY=VALUE overrides, or resource limits). Those values are dropped here and
            # the limit fields are re-derived from persona/server defaults in the view.
            cleaned_data["plugins"] = []
            cleaned_data["plugin_config"] = {}
            cleaned_data["config"] = {}
            permission = str(cleaned_data.get("permissions") or "").strip().lower()
            if not self.is_authenticated_user or permission not in {PERMISSIONS_PUBLIC, PERMISSIONS_UNLISTED}:
                permission = PERMISSIONS_PUBLIC
            cleaned_data["permissions"] = permission
            return cleaned_data

        # Combine all plugin groups into single list
        all_selected_plugins = []
        for field in [
            "main_plugins",
            "page_setup_plugins",
            "media_plugins",
            "text_plugins",
            "metadata_plugins",
            "postprocessing_plugins",
            "other_plugins",
        ]:
            selected = cleaned_data.get(field)
            if isinstance(selected, list):
                all_selected_plugins.extend(selected)

        # Store combined list for easy access
        cleaned_data["plugins"] = all_selected_plugins

        plugin_config_overrides = self.clean_plugin_config_overrides(get_config(persona=cleaned_data.get("persona")))
        custom_config = cleaned_data.get("config") or {}
        if not isinstance(custom_config, dict):
            custom_config = {}
        cleaned_data["plugin_config"] = plugin_config_overrides
        cleaned_data["config"] = {**plugin_config_overrides, **custom_config}

        return cleaned_data

    def clean_url(self):
        value = self.cleaned_data.get("url") or ""
        valid_urls = []
        for url in find_all_urls(value):
            valid_urls.append(url)
        if not valid_urls:
            raise forms.ValidationError("Enter at least one valid URL.")
        return "\n".join(valid_urls)

    def clean_url_filters(self):
        from archivebox.crawls.models import Crawl

        value = self.cleaned_data.get("url_filters") or {}
        return {
            "allowlist": "\n".join(Crawl.split_filter_patterns(value.get("allowlist", ""))),
            "denylist": "\n".join(Crawl.split_filter_patterns(value.get("denylist", ""))),
            "same_domain_only": bool(value.get("same_domain_only")),
            "subpaths_only": bool(value.get("subpaths_only")),
            "only_new": bool(value.get("only_new")),
        }

    def clean_max_urls(self):
        value = self.cleaned_data.get("max_urls")
        return int(value or 0)

    def clean_crawl_max_size(self):
        raw_value = str(self.cleaned_data.get("crawl_max_size") or "").strip()
        if not raw_value:
            return 0
        try:
            value = parse_filesize_to_bytes(raw_value)
        except ValueError as err:
            raise forms.ValidationError(str(err))
        if value < 0:
            raise forms.ValidationError("Max crawl size must be 0 or a positive number of bytes.")
        return value

    def clean_crawl_timeout(self):
        return self._clean_timeout_seconds(self.cleaned_data.get("crawl_timeout"), "Max crawl time", blank_value=0)

    def clean_timeout(self):
        return self._clean_timeout_seconds(self.cleaned_data.get("timeout"), "Max subtask time", blank_value=None)

    def _clean_timeout_seconds(self, raw_value, field_label: str, *, blank_value):
        raw_value = str(raw_value or "").strip().lower()
        if not raw_value:
            return blank_value
        if raw_value.isdigit():
            value = int(raw_value)
        else:
            match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)", raw_value)
            if not match:
                raise forms.ValidationError(f"{field_label} must be seconds or a duration like 1.5m or 1hr.")
            amount_str, unit = match.groups()
            try:
                amount = Decimal(amount_str)
            except InvalidOperation as err:
                raise forms.ValidationError(f"{field_label} must be seconds or a duration like 1.5m or 1hr.") from err
            multiplier = 1
            if unit in {"m", "min", "mins", "minute", "minutes"}:
                multiplier = 60
            elif unit in {"h", "hr", "hrs", "hour", "hours"}:
                multiplier = 60 * 60
            value = int((amount * multiplier).to_integral_value(rounding=ROUND_CEILING))
        if 0 < value <= 10:
            raise forms.ValidationError(f"{field_label} must be 0 or greater than 10 seconds.")
        return value

    def clean_snapshot_max_size(self):
        raw_value = str(self.cleaned_data.get("snapshot_max_size") or "").strip()
        if not raw_value:
            return 0
        try:
            value = parse_filesize_to_bytes(raw_value)
        except ValueError as err:
            raise forms.ValidationError(str(err))
        if value < 0:
            raise forms.ValidationError("Max snapshot size must be 0 or a positive number of bytes.")
        return value

    def clean_delete_after(self):
        raw_value = str(self.cleaned_data.get("delete_after") or "0").strip() or "0"
        try:
            parse_delete_after(raw_value)
        except ValueError as err:
            raise forms.ValidationError(str(err))
        return raw_value

    def clean_crawl_max_concurrent_snapshots(self):
        value = self.cleaned_data.get("crawl_max_concurrent_snapshots")
        if value in (None, ""):
            value = get_config().CRAWL_MAX_CONCURRENT_SNAPSHOTS
        value = int(value)
        if value < 1:
            raise forms.ValidationError("Max concurrent snapshots must be at least 1.")
        return value

    def clean_schedule(self):
        schedule = (self.cleaned_data.get("schedule") or "").strip()
        if not schedule:
            return ""

        try:
            validate_schedule(schedule)
        except ValueError as err:
            raise forms.ValidationError(str(err))

        return schedule


class TagWidget(forms.TextInput):
    def format_value(self, value):
        if value is not None and not isinstance(value, str):
            value = edit_string_for_tags(value)
        return super().format_value(value)


class TagField(forms.CharField):
    widget = TagWidget

    def clean(self, value):
        value = super().clean(value)
        try:
            return parse_tags(value)
        except ValueError:
            raise forms.ValidationError(
                "Please provide a comma-separated list of tags.",
            )

    def has_changed(self, initial, data):
        # Always return False if the field is disabled since self.bound_data
        # always uses the initial value in this case.
        if self.disabled:
            return False

        try:
            cleaned_data = self.clean(data)
        except forms.ValidationError:
            cleaned_data = data

        initial_value = [] if initial is None else initial

        if not isinstance(initial_value, list):
            initial_value = list(initial_value)

        normalized_initial = sorted(tag.name for tag in initial_value)
        return normalized_initial != cleaned_data
