__package__ = "archivebox.plugins"

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from django import forms
from django.utils.html import format_html

from archivebox.config import CONSTANTS_CONFIG
from archivebox.config.common import ArchiveBoxConfig, get_config
from archivebox.plugins.discovery import discover_plugin_configs, get_plugin_catalog, get_plugin_icon, get_plugins


PLUGIN_CONFIG_FIELD_PREFIX = "plugin_config__"
PLUGIN_GROUPS = (
    ("main", "main_plugins", "Main"),
    ("page_setup", "page_setup_plugins", "Page Setup"),
    ("media", "media_plugins", "Media"),
    ("text", "text_plugins", "Text"),
    ("metadata", "metadata_plugins", "Metadata"),
    ("postprocessing", "postprocessing_plugins", "Postprocessing"),
    ("other", "other_plugins", "Other"),
)
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
        '<span class="plugin-choice-icon">{}</span><span class="plugin-choice-name">{}</span>',
        icon_html,
        plugin_name,
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
    allow_crawl_execution_config_fields = True

    def build_plugin_groups(self, runtime_config: Mapping[str, Any] | None = None) -> None:
        catalog = get_plugin_catalog()
        all_plugins = set(catalog)
        plugin_configs = discover_plugin_configs()
        runtime_config = runtime_config or get_config()
        self.plugin_config_binary_urls = get_plugin_config_binary_urls(runtime_config)
        grouped_plugins = catalog.groups()

        group_specs = []
        for category, field_name, title in PLUGIN_GROUPS:
            plugin_names = tuple(plugin.name for plugin in grouped_plugins.get(category, []))
            group_specs.append((field_name, title, "", "", "", plugin_names))
            if field_name in self.fields:
                get_choice_field(self, field_name).choices = [
                    (p, get_plugin_choice_label(p, plugin_configs)) for p in plugin_names if p in all_plugins
                ]
        binary_url_lookup = _build_required_binary_url_lookup(plugin_configs, runtime_config)
        self.plugin_groups = [
            {
                "field_name": field_name,
                "title": title,
                "note": note,
                "dom_id": dom_id,
                "select_all_group": select_all_group,
                "show_selectors": field_name in self.fields,
                "plugins": self._build_plugin_cards(field_name, plugin_names, plugin_configs, runtime_config, binary_url_lookup),
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
        binary_url_lookup: Mapping[str, str] | None = None,
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
                if (
                    isinstance(prop_schema, dict)
                    and str(config_key) not in CONSTANTS_CONFIG
                    and (self.allow_crawl_execution_config_fields or ArchiveBoxConfig.scope_for_key(str(config_key)) == "crawl_frozen")
                )
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
                    "required_binary_links": _build_required_binary_links(
                        schema.get("required_binaries") or [],
                        runtime_config,
                        binary_url_lookup,
                    ),
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
        from archivebox.config.common import is_sensitive_config_key

        is_sensitive = bool(prop_schema.get("x-sensitive")) or is_sensitive_config_key(config_key)
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
        else:
            input_value = "" if is_sensitive else str(current_value)

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
            "current": "configured"
            if is_sensitive and current_value
            else (str(current_value) if "string" in schema_types else _jsonish(current_value)),
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
                if str(config_key) in CONSTANTS_CONFIG:
                    continue
                if not self.allow_crawl_execution_config_fields and ArchiveBoxConfig.scope_for_key(str(config_key)) != "crawl_frozen":
                    continue

                raw_value: Any = self.data.get(input_name)
                if "array" in _schema_types(prop_schema) and isinstance(prop_schema.get("enum"), list):
                    raw_value = self.data.getlist(input_name)

                from archivebox.config.common import SENSITIVE_CONFIG_VALUE_REDACTED, is_sensitive_config_key

                if (prop_schema.get("x-sensitive") or is_sensitive_config_key(config_key)) and raw_value in (
                    "",
                    SENSITIVE_CONFIG_VALUE_REDACTED,
                ):
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


_BINARY_TEMPLATE_PATTERN = re.compile(r"\{([A-Z_][A-Z0-9_]*)\}")


def _resolve_required_binary_name(template_name: str, runtime_config: Mapping[str, Any]) -> str:
    if "{" not in template_name:
        return template_name

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        try:
            value = runtime_config.get(key)
        except Exception:
            value = None
        if value is None or value == "":
            return match.group(0)
        return str(value)

    resolved = _BINARY_TEMPLATE_PATTERN.sub(_replace, template_name).strip()
    if not resolved:
        return template_name
    return Path(resolved).name if "/" in resolved else resolved


def _iter_required_binary_names(
    required_binaries: Iterable[Any],
    runtime_config: Mapping[str, Any],
) -> Iterable[str]:
    for item in required_binaries or []:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or "").strip()
        if not raw_name:
            continue
        resolved = _resolve_required_binary_name(raw_name, runtime_config)
        if resolved:
            yield resolved


def _build_required_binary_url_lookup(
    plugin_configs: Mapping[str, dict[str, Any]],
    runtime_config: Mapping[str, Any],
) -> dict[str, str]:
    """Resolve admin URLs for every required binary across all plugin schemas in a single DB query."""
    from archivebox.config.views import get_environment_binary_url, get_installed_binary_change_url
    from archivebox.machine.models import Binary, Machine

    resolved_names: set[str] = set()
    for schema in plugin_configs.values():
        for name in _iter_required_binary_names(schema.get("required_binaries") or [], runtime_config):
            resolved_names.add(name)

    if not resolved_names:
        return {}

    machine = Machine.current()
    name_to_binary: dict[str, Binary] = {}
    for binary in (
        Binary.objects.filter(machine=machine, name__in=resolved_names)
        .exclude(abspath="")
        .exclude(abspath__isnull=True)
        .order_by("-modified_at")
    ):
        key = binary.name.lower()
        if key not in name_to_binary:
            name_to_binary[key] = binary

    return {
        name: (get_installed_binary_change_url(name, name_to_binary.get(name.lower())) or get_environment_binary_url(name))
        for name in resolved_names
    }


def _build_required_binary_links(
    required_binaries: list[dict[str, Any]],
    runtime_config: Mapping[str, Any],
    binary_url_lookup: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    from archivebox.config.views import get_environment_binary_url

    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for resolved in _iter_required_binary_names(required_binaries, runtime_config):
        if resolved in seen:
            continue
        seen.add(resolved)
        url = (binary_url_lookup or {}).get(resolved) or get_environment_binary_url(resolved)
        links.append({"name": resolved, "url": url})
    return links


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
        binary_name = binary.name if binary is not None else name
        urls[key] = get_installed_binary_change_url(binary_name, binary) or get_environment_binary_url(name)
    return urls
