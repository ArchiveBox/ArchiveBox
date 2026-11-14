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
from archivebox.plugins.documentation import get_plugin_documentation
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


def _config_label(name: str) -> str:
    acronyms = {"api", "css", "fps", "html", "http", "https", "id", "json", "pdf", "ssl", "ui", "url", "urls"}
    words = name.replace("_", " ").split()
    return " ".join(
        word.upper() if word.lower() in acronyms else (word.capitalize() if index == 0 else word.lower())
        for index, word in enumerate(words)
    )


def get_plugin_choice_label(plugin_name: str, plugin_configs: dict[str, dict]) -> str:
    schema = plugin_configs.get(plugin_name, {})
    description = str(schema.get("description") or "").strip()
    if not description:
        return plugin_name
    icon_html = get_plugin_icon(plugin_name)

    return format_html(
        '<span class="plugin-choice-icon">{}</span><span class="plugin-choice-name">{}</span>',
        icon_html,
        str(schema.get("title") or _config_label(plugin_name)),
    )


def get_choice_field(form: forms.Form, name: str) -> forms.ChoiceField:
    field = form.fields[name]
    if not isinstance(field, forms.ChoiceField):
        raise TypeError(f"{name} must be a ChoiceField")
    return field


def _plugin_config_input_name(plugin_name: str, config_key: str) -> str:
    return f"{PLUGIN_CONFIG_FIELD_PREFIX}{plugin_name}__{config_key}"


def _schema_types(schema: Mapping[str, Any]) -> list[str]:
    if "anyOf" in schema:
        return [kind for option in schema["anyOf"] for kind in _schema_types(option)]
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
    if raw_value == "" and "null" in schema_types:
        return None

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
    pattern = schema.get("pattern")
    if pattern and not re.search(pattern, value):
        raise forms.ValidationError("Does not match the required format.")
    enum = schema.get("enum")
    if isinstance(enum, list) and enum and value not in {str(item) for item in enum}:
        raise forms.ValidationError(f"Must be one of: {', '.join(str(item) for item in enum)}.")
    return value


class PluginConfigFormMixin:
    plugin_groups: list[dict[str, Any]]
    plugin_group_specs = PLUGIN_GROUPS
    allow_crawl_execution_config_fields = True
    settings_scopes = None

    def settings_schemas(self):
        derived = ArchiveBoxConfig.runtime_derived_config_keys() | set(ArchiveBoxConfig.computed_config_keys)
        schemas = {
            name: {
                **schema,
                "properties": {
                    key: prop
                    for key, prop in (schema.get("properties") or {}).items()
                    if key not in derived and (self.settings_scopes is None or ArchiveBoxConfig.scope_for_key(key) in self.settings_scopes)
                },
            }
            for name, schema in discover_plugin_configs().items()
        }
        if getattr(self, "include_core_settings", False):
            from archivebox.config.common import config_field_metadata

            schemas["archivebox"] = {
                "properties": {
                    key: meta["schema"]
                    for key, meta in config_field_metadata(include_execution=True).items()
                    if meta["plugin"] == "archivebox"
                    and key.isupper()
                    and key not in CONSTANTS_CONFIG
                    and key not in derived
                    and key != "SECRET_KEY"
                    and (key != "PERMISSIONS" or getattr(self, "system_settings", False))
                    and (getattr(self, "system_settings", False) or meta["scope"] in {"crawl_frozen", "crawl_execution"})
                },
            }
        return schemas

    def merge_settings(self, config, inherited):
        """Patch only edited fields; opening and saving never pins inherited defaults."""
        merged = dict(config or {})
        changed = self.data.getlist("settings_changed") if "settings_editor" in self.data else None
        overrides = self.clean_plugin_config_overrides(inherited, omit_inherited=False)
        for plugin, schema in self.settings_schemas().items():
            for key, prop in schema.get("properties", {}).items():
                name = _plugin_config_input_name(plugin, key)
                if name not in self.data or (changed is not None and key not in changed):
                    continue
                from archivebox.config.common import SENSITIVE_CONFIG_VALUE_REDACTED, is_sensitive_config_key

                if (prop.get("x-sensitive") or is_sensitive_config_key(key)) and self.data.get(name) in (
                    "",
                    SENSITIVE_CONFIG_VALUE_REDACTED,
                ):
                    continue
                if changed is None and key in merged:
                    try:
                        if _same_config_value(_coerce_plugin_config_value(self.data.get(name), prop), merged[key]):
                            overrides.pop(key, None)
                            continue
                    except (TypeError, ValueError, forms.ValidationError):
                        pass  # The field cleaner reports this error.
                merged.pop(key, None)
        merged.update(overrides)
        from pydantic import ValidationError

        try:
            for key, value in overrides.items():
                without_key = {name: item for name, item in merged.items() if name != key}
                baseline = self.resolve_settings(without_key)
                if _same_config_value(value, baseline.get(key)) or (value == "" and baseline.get(key) is None):
                    merged.pop(key, None)
            self.resolve_settings(merged)
        except ValidationError as err:
            for error in err.errors(include_url=False, include_input=False):
                self.add_error("config", f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}")
        from archivebox.config.rule_views import url_rule_errors

        for error in url_rule_errors(
            merged.get("URL_ALLOWLIST", inherited.get("URL_ALLOWLIST")) or "",
            merged.get("URL_DENYLIST", inherited.get("URL_DENYLIST")) or "",
        ):
            self.add_error("config", f"URL_{error['field'].upper()}: {error['message']}")
        return merged

    def build_plugin_groups(self, runtime_config: Mapping[str, Any] | None = None) -> None:
        catalog = get_plugin_catalog()
        all_plugins = set(catalog)
        plugin_configs = self.settings_schemas()
        runtime_config = runtime_config or get_config()
        binary_url_lookup = build_required_binary_url_lookup(plugin_configs, [runtime_config])
        self.plugin_config_binary_urls = get_plugin_config_binary_urls(runtime_config, binary_url_lookup)
        grouped_plugins = catalog.groups()

        category_specs = list(self.plugin_group_specs)
        known_categories = {category for category, _field_name, _title in category_specs}
        # Importers are source commands rather than capture selections. Pages
        # that expose their settings opt in through plugin_group_specs.
        extra_categories = sorted(set(grouped_plugins) - known_categories - {"importers"})
        category_specs.extend((category, "other_plugins", _config_label(category)) for category in extra_categories)
        group_specs = []
        field_choices: dict[str, list[tuple[str, str]]] = {}
        for category, field_name, title in category_specs:
            plugin_names = tuple(plugin.name for plugin in grouped_plugins.get(category, []))
            group_specs.append((field_name, title, "", "", "", plugin_names))
            if field_name in self.fields:
                field_choices.setdefault(field_name, []).extend(
                    (p, get_plugin_choice_label(p, plugin_configs)) for p in plugin_names if p in all_plugins
                )
        for field_name, choices in field_choices.items():
            get_choice_field(self, field_name).choices = choices
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
        if getattr(self, "include_core_settings", False):
            from archivebox.config.common import find_config_section

            grouped = {card["name"] for group in self.plugin_groups for card in group["plugins"]}
            ungrouped = sorted(all_plugins - grouped)
            cards = self._build_plugin_cards("shared_settings", ungrouped, plugin_configs, runtime_config, binary_url_lookup)
            cards = [card for card in cards if card["config_fields"]]
            if cards:
                self.plugin_groups.append({"field_name": "shared_settings", "title": "Other", "plugins": cards})
            sections = {}
            for key, schema in self.settings_schemas()["archivebox"]["properties"].items():
                sections.setdefault(find_config_section(key), []).append(
                    self._build_plugin_config_field("archivebox", key, schema, runtime_config),
                )
            self.plugin_groups.insert(
                0,
                {
                    "field_name": "system",
                    "title": "" if getattr(self, "system_settings", False) else "Capture defaults",
                    "plugins": [
                        {
                            "name": section.lower(),
                            "is_core": True,
                            "label": _config_label(section.removesuffix("_CONFIG")),
                            "config_fields": fields,
                            "description": "",
                            "config_count": len(fields),
                            "system_default": getattr(self, "system_settings", False)
                            and all(
                                ArchiveBoxConfig.scope_for_key(field["key"]) in {"crawl_frozen", "crawl_execution"} for field in fields
                            ),
                        }
                        for section, fields in sorted(sections.items(), key=lambda item: item[0] != "ARCHIVING_CONFIG")
                    ],
                },
            )
        if getattr(self, "system_settings", False):
            for group in self.plugin_groups:
                for card in group["plugins"]:
                    if not card.get("is_core"):
                        card["system_default"] = True
        if self.plugin_groups:
            self.plugin_groups[0]["changed_keys"] = self.data.getlist("settings_changed") if self.is_bound else []
        for group in self.plugin_groups:
            for card in group["plugins"]:
                fields = [field for field in card["config_fields"] if field["key"] != card.get("enabled_config_key")]
                card["primary_fields"] = [field for field in fields if not field["advanced"]]
                card["advanced_fields"] = [field for field in fields if field["advanced"]]

    def _build_plugin_cards(
        self,
        field_name: str,
        plugin_names: Iterable[str],
        plugin_configs: dict[str, dict[str, Any]],
        runtime_config: Mapping[str, Any],
        binary_url_lookup: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        plugin_names = tuple(plugin_names)
        if field_name in self.fields:
            choices = list(get_choice_field(self, field_name).choices)
            selected_values = set(self.data.getlist(field_name)) if self.is_bound else set(get_choice_field(self, field_name).initial or [])
        else:
            all_plugins = get_plugins()
            choices = [(p, get_plugin_choice_label(p, plugin_configs)) for p in plugin_names if p in all_plugins]
            selected_values = set()

        cards = []
        for index, (plugin_name, label) in enumerate(choices):
            # New categories share other_plugins on /add/, but each panel only
            # includes its own plugins. Keep aggregate indices for unique IDs.
            if plugin_name not in plugin_names:
                continue
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
                    "enabled_field": next((field for field in config_fields if field["key"] == enabled_config_key), None),
                    "description": str(schema.get("description") or "").strip(),
                    "source_url": f"https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/{plugin_name}",
                    **get_plugin_documentation(str(plugin_name)),
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
        if "anyOf" in prop_schema:
            prop_schema = {**next((part for part in prop_schema["anyOf"] if part.get("type") != "null"), {}), **prop_schema}
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
            input_value = "" if current_value is None else str(current_value)

        description = str(prop_schema.get("description") or "").strip()
        quantity_kind = ""
        unit = "s"
        quantity_format = "base"
        if field_kind == "number":
            if config_key.endswith("_BYTES") or re.search(r"\bbytes\b", description, re.I):
                quantity_kind, unit = "bytes", "B"
            elif "TIMEOUT" in config_key or re.search(r"_(?:DELAY|WAIT|INTERVAL|BUDGET)(?:_|$)", config_key):
                if "TIMEOUT" in config_key or re.search(r"\b(?:seconds?|milliseconds?|ms)\b", description, re.I):
                    quantity_kind = "duration"
                    unit = "ms" if re.search(r"\b(?:milliseconds?|ms)\b", description, re.I) or config_key.endswith("_MS") else "s"
        elif field_kind == "text" and prop_schema.get("pattern") == r"^\d+[kmgKMG]?$":
            quantity_kind, unit, quantity_format = "bytes", "B", "size-suffix"
        elif config_key == "DELETE_AFTER":
            quantity_kind, unit, quantity_format = "duration", "s", "retention"

        plugin_choices = []
        if config_key in {"PLUGINS", "CRAWL_DISCOVERY_PLUGINS"}:
            plugin_choices = [
                {"value": name, "label": str(plugin.manifest.get("title") or _config_label(name))}
                for name, plugin in get_plugin_catalog().items()
                if not plugin.config.hidden and plugin.config.category != "importers"
            ]
        placeholder = str((prop_schema.get("examples") or [None])[0] or input_value or _jsonish(default_value))
        if plugin_choices and not input_value:
            enabled = [item["value"] for item in plugin_choices if runtime_config.get(f"{item['value'].upper()}_ENABLED", True)]
            placeholder = ", ".join(enabled[:3])

        return {
            "key": config_key,
            "label": _config_label(config_key)
            if plugin_name == "archivebox"
            else str(prop_schema.get("title") or _config_label(config_key.removeprefix(f"{plugin_name.upper()}_"))),
            "input_name": input_name,
            "kind": field_kind,
            "is_timeout": field_kind == "number" and "TIMEOUT" in config_key,
            "unit": unit,
            "quantity_kind": quantity_kind,
            "quantity_format": quantity_format,
            "input_type": input_type,
            "value": input_value,
            "checked": bool(current_value),
            "options": options,
            "description": str(prop_schema.get("description") or "").strip(),
            "default": _jsonish(default_display),
            "current": "configured"
            if is_sensitive and current_value
            else (("" if current_value is None else str(current_value)) if "string" in schema_types else _jsonish(current_value)),
            "current_url": self.plugin_config_binary_urls.get(config_key, "") if str(config_key).endswith("_BINARY") else "",
            "is_sensitive": is_sensitive,
            "step": "any" if "number" in schema_types else "1",
            "minimum": prop_schema.get("minimum"),
            "maximum": prop_schema.get("maximum"),
            "pattern": prop_schema.get("pattern"),
            "type_label": " / ".join(schema_types),
            "placeholder": "" if is_sensitive else placeholder,
            "plugin_choices": plugin_choices,
            "source": getattr(self, "settings_sources", {}).get(config_key, ""),
            "advanced": bool(prop_schema.get("x-advanced"))
            or bool(re.search(r"(?:_BINARY(?:_ARGS)?|_ARGS|_DIR|_PATH|_PORT|_ENDPOINT)$", config_key)),
            "range_max": prop_schema.get("maximum", 100 * 1024**3 if quantity_kind == "bytes" else (86400000 if unit == "ms" else 86400)),
            "exclusive_minimum": prop_schema.get("exclusiveMinimum"),
        }

    def clean_plugin_config_overrides(
        self,
        effective_config: Mapping[str, Any] | None = None,
        *,
        omit_inherited: bool = True,
    ) -> dict[str, Any]:
        if not self.is_bound:
            return {}

        effective_config = effective_config or get_config()
        overrides: dict[str, Any] = {}
        sources: dict[str, str] = {}

        changed = self.data.getlist("settings_changed") if "settings_editor" in self.data else None
        for plugin_name, schema in self.settings_schemas().items():
            for config_key, prop_schema in (schema.get("properties") or {}).items():
                if not isinstance(prop_schema, dict):
                    continue

                input_name = _plugin_config_input_name(plugin_name, config_key)
                if input_name not in self.data:
                    continue
                if changed is not None and config_key not in changed:
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
                    if raw_value == "" and changed is not None and config_key in changed:
                        self.add_error("config", forms.ValidationError(f"{config_key}: enter the value again."))
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
                if omit_inherited and base_value is None and coerced_value == "":
                    continue
                if omit_inherited and _same_config_value(coerced_value, base_value):
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


def build_required_binary_url_lookup(
    plugin_configs: Mapping[str, dict[str, Any]],
    runtime_configs: Iterable[Mapping[str, Any]],
) -> dict[str, str]:
    """Resolve required/configured binary links for all configs in one DB query."""
    from django.db.models import Q
    from django.db.models.functions import Lower
    from archivebox.config.views import get_environment_binary_url, get_installed_binary_change_url
    from archivebox.machine.models import Binary, Machine

    resolved_names: set[str] = set()
    for runtime_config in runtime_configs:
        for schema in plugin_configs.values():
            for name in _iter_required_binary_names(schema.get("required_binaries") or [], runtime_config):
                resolved_names.add(name)
            for key in schema.get("properties") or {}:
                if key.endswith("_BINARY") and (value := str(runtime_config.get(key) or "").strip()):
                    resolved_names.add(value)

    if not resolved_names:
        return {}

    machine = Machine.current()
    name_to_binary: dict[str, Binary] = {}
    path_to_binary: dict[str, Binary] = {}
    names = {name.lower() for name in resolved_names}
    names.update(Path(name).name.lower() for name in resolved_names if "/" in name)
    for binary in (
        Binary.objects.filter(machine=machine)
        .alias(normalized_name=Lower("name"))
        .filter(Q(normalized_name__in=names) | Q(abspath__in=resolved_names))
        .exclude(abspath="")
        .exclude(abspath__isnull=True)
        .order_by("-modified_at")
    ):
        key = binary.name.lower()
        if key not in name_to_binary:
            name_to_binary[key] = binary
        path_to_binary.setdefault(binary.abspath, binary)

    urls = {}
    for value in resolved_names:
        name = Path(value).name if "/" in value else value
        binary = name_to_binary.get(value.lower())
        if binary is None and "/" in value:
            binary = path_to_binary.get(value) or name_to_binary.get(name.lower())
        binary_name = binary.name if binary is not None else name
        urls[value] = get_installed_binary_change_url(binary_name, binary) or get_environment_binary_url(name)
    return urls


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


def get_plugin_config_binary_urls(
    runtime_config: Mapping[str, Any],
    binary_url_lookup: Mapping[str, str] | None = None,
) -> dict[str, str]:
    plugin_configs = discover_plugin_configs()
    binary_keys = {
        str(config_key)
        for schema in plugin_configs.values()
        for config_key, prop_schema in (schema.get("properties") or {}).items()
        if isinstance(prop_schema, dict) and str(config_key).endswith("_BINARY")
    }
    if binary_url_lookup is None:
        binary_url_lookup = build_required_binary_url_lookup(plugin_configs, [runtime_config])
    urls: dict[str, str] = {}
    for key in binary_keys:
        value = str(runtime_config.get(key) or "").strip()
        if not value:
            continue
        urls[key] = binary_url_lookup[value]
    return urls
