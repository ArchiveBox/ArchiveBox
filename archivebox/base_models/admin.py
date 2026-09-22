"""Base admin classes for models using UUIDv7."""

__package__ = "archivebox.base_models"

import json
import uuid
from collections.abc import Mapping
from typing import ClassVar, NotRequired, TypedDict, cast

from django import forms
from django.contrib import admin
from django.db import DatabaseError, models
from django.forms.renderers import BaseRenderer
from django.http import HttpRequest, QueryDict
from django.urls import path, register_converter
from django.utils.safestring import SafeString, mark_safe
from django_object_actions import DjangoObjectActions


class HexUUIDConverter:
    """URL path converter that canonicalizes UUIDs to their 32-char hex form.

    Accepts both the hyphenated (``aaaaaaaa-bbbb-...``) and bare-hex
    (``aaaaaaaabbbb...``) UUID strings on the way in (Django's UUIDField
    parses either), but ``to_url`` always emits the bare-hex form. This is
    what makes ``reverse("admin:app_model_change", args=[obj.pk])`` produce
    ``/admin/app/model/06a1a8facb0d.../change/`` instead of the default
    hyphenated rendering — admin links throughout the app reverse through
    this converter once ``BaseModelAdmin.get_urls`` swaps in
    ``<hexuuid:object_id>`` below.
    """

    regex = r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

    def to_python(self, value: str) -> str:
        # Strip hyphens but stay as a string — Django admin treats the
        # captured object_id as a string and calls ``model._meta.pk.to_python``
        # itself, so we don't want to short-circuit that.
        return value.replace("-", "")

    def to_url(self, value) -> str:
        if isinstance(value, uuid.UUID):
            return value.hex
        return str(value).replace("-", "")


register_converter(HexUUIDConverter, "hexuuid")


class ConfigOption(TypedDict):
    plugin: str
    type: str | list[str]
    default: object
    description: str
    enum: NotRequired[list[object]]
    pattern: NotRequired[str]
    minimum: NotRequired[int | float]
    maximum: NotRequired[int | float]


class KeyValueWidget(forms.Widget):
    """
    A widget that renders JSON dict as editable key-value input fields
    with + and - buttons to add/remove rows.
    Includes autocomplete for available config keys from the plugin system.
    """

    template_name = ""  # We render manually

    class Media:
        css: ClassVar[dict[str, list[str]]] = {
            "all": [],
        }
        js: ClassVar[list[str]] = []

    def _get_config_options(self) -> dict[str, ConfigOption]:
        """Get available config options from plugins."""
        try:
            from archivebox.config.common import config_field_metadata

            options: dict[str, ConfigOption] = {}
            for key, metadata in config_field_metadata().items():
                option_type = metadata.get("type", "string")
                option: ConfigOption = {
                    "plugin": str(metadata.get("plugin", "archivebox")),
                    "type": cast(str | list[str], option_type if isinstance(option_type, (str, list)) else str(option_type)),
                    "default": metadata.get("default", ""),
                    "description": str(metadata.get("description", "")),
                }
                schema = metadata.get("schema")
                if isinstance(schema, Mapping):
                    for schema_key in ("enum", "pattern", "minimum", "maximum"):
                        if schema_key in schema:
                            option[schema_key] = schema[schema_key]
                options[key] = option
            return options
        except (ImportError, KeyError, TypeError, ValueError):
            return {}

    def _parse_value(self, value: object) -> dict[str, object]:
        # Parse JSON value to dict
        if value is None:
            return {}
        if isinstance(value, str):
            try:
                parsed = json.loads(value) if value else {}
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        if isinstance(value, Mapping):
            return {str(key): item for key, item in value.items()}
        return {}

    def render(
        self,
        name: str,
        value: object,
        attrs: Mapping[str, str] | None = None,
        renderer: BaseRenderer | None = None,
    ) -> SafeString:
        data = self._parse_value(value)

        widget_id = attrs.get("id", name) if attrs else name
        config_options = self._get_config_options()

        # Build datalist options
        datalist_options = "\n".join(
            f'<option value="{self._escape(key)}">{self._escape(opt["description"][:60] or opt["type"])}</option>'
            for key, opt in sorted(config_options.items())
        )

        # Build config metadata as JSON for JS
        config_meta_json = json.dumps(config_options)

        html = f'''
        <div id="{widget_id}_container" class="key-value-editor" style="width: 100%; max-width: none;">
            <datalist id="{widget_id}_keys">
                {datalist_options}
            </datalist>
            <div id="{widget_id}_rows" class="key-value-rows">
        '''

        # Render existing key-value pairs
        for key, val in data.items():
            val_str = json.dumps(val) if not isinstance(val, str) else val
            html += self._render_row(widget_id, key, val_str)

        # Always add one empty row for new entries
        html += self._render_row(widget_id, "", "")

        html += f'''
            </div>
            <div style="display: flex; gap: 8px; align-items: center; margin-top: 8px;">
                <button type="button" onclick="addKeyValueRow_{widget_id}()"
                        style="padding: 4px 12px; cursor: pointer; background: #417690; color: white; border: none; border-radius: 4px;">
                    + Add Row
                </button>
            </div>
            <input type="hidden" name="{name}" id="{widget_id}" value="">
            <script>
                (function() {{
                    var configMeta_{widget_id} = {config_meta_json};
                    var rowCounter_{widget_id} = 0;

                    function stringifyValue_{widget_id}(value) {{
                        return typeof value === 'string' ? value : JSON.stringify(value);
                    }}

                    function getTypes_{widget_id}(meta) {{
                        if (!meta || meta.type === undefined || meta.type === null) {{
                            return [];
                        }}
                        return Array.isArray(meta.type) ? meta.type : [meta.type];
                    }}

                    function getMetaForKey_{widget_id}(key) {{
                        if (!key) {{
                            return null;
                        }}

                        var explicitMeta = configMeta_{widget_id}[key];
                        if (explicitMeta) {{
                            return Object.assign({{ key: key }}, explicitMeta);
                        }}

                        if (key.endsWith('_BINARY')) {{
                            return {{
                                key: key,
                                plugin: 'custom',
                                type: 'string',
                                default: '',
                                description: 'Path to binary executable',
                            }};
                        }}

                        if (isRegexConfigKey_{widget_id}(key)) {{
                            return {{
                                key: key,
                                plugin: 'custom',
                                type: 'string',
                                default: '',
                                description: 'Regex pattern list',
                            }};
                        }}

                        return null;
                    }}

                    function describeMeta_{widget_id}(meta) {{
                        if (!meta) {{
                            return '';
                        }}

                        var details = '';
                        if (Array.isArray(meta.enum) && meta.enum.length) {{
                            details = 'Allowed: ' + meta.enum.map(stringifyValue_{widget_id}).join(', ');
                        }} else {{
                            var types = getTypes_{widget_id}(meta);
                            if (types.length) {{
                                details = 'Expected: ' + types.join(' or ');
                            }}
                        }}

                        if (meta.minimum !== undefined || meta.maximum !== undefined) {{
                            var bounds = [];
                            if (meta.minimum !== undefined) bounds.push('min ' + meta.minimum);
                            if (meta.maximum !== undefined) bounds.push('max ' + meta.maximum);
                            details += (details ? ' ' : '') + '(' + bounds.join(', ') + ')';
                        }}

                        return [meta.description || '', details].filter(Boolean).join(' ');
                    }}

                    function getExampleInput_{widget_id}(key, meta) {{
                        var types = getTypes_{widget_id}(meta);
                        if (key.endsWith('_BINARY')) {{
                            return 'Example: wget or /usr/bin/wget';
                        }}
                        if (key.endsWith('_ARGS_EXTRA') || key.endsWith('_ARGS')) {{
                            return 'Example: ["--extra-arg"]';
                        }}
                        if (types.includes('array')) {{
                            return 'Example: ["value"]';
                        }}
                        if (types.includes('object')) {{
                            return 'Example: {{"key": "value"}}';
                        }}
                        return '';
                    }}

                    function isRegexConfigKey_{widget_id}(key) {{
                        return key === 'URL_ALLOWLIST' ||
                            key === 'URL_DENYLIST' ||
                            key.endsWith('_PATTERN') ||
                            key.includes('REGEX');
                    }}

                    function isSimpleFilterPattern_{widget_id}(pattern) {{
                        return /^[\\w.*:-]+$/.test(pattern);
                    }}

                    function validateRegexPattern_{widget_id}(pattern) {{
                        if (!pattern || isSimpleFilterPattern_{widget_id}(pattern)) {{
                            return '';
                        }}

                        try {{
                            new RegExp(pattern);
                        }} catch (error) {{
                            return error && error.message ? error.message : 'Invalid regex';
                        }}
                        return '';
                    }}

                    function validateRegexConfig_{widget_id}(key, raw, typeName) {{
                        if (typeName === 'object') {{
                            var parsed;
                            try {{
                                parsed = JSON.parse(raw);
                            }} catch (error) {{
                                return {{ ok: false, value: raw, message: 'Must be valid JSON' }};
                            }}
                            if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {{
                                return {{ ok: false, value: parsed, message: 'Must be a JSON object' }};
                            }}
                            for (var regexKey in parsed) {{
                                var objectRegexError = validateRegexPattern_{widget_id}(regexKey);
                                if (objectRegexError) {{
                                    return {{ ok: false, value: parsed, message: 'Invalid regex key "' + regexKey + '": ' + objectRegexError }};
                                }}
                            }}
                            return {{ ok: true, value: parsed, message: '' }};
                        }}

                        var patterns = raw.split(/[\\n,]+/).map(function(pattern) {{
                            return pattern.trim();
                        }}).filter(Boolean);
                        for (var i = 0; i < patterns.length; i++) {{
                            var regexError = validateRegexPattern_{widget_id}(patterns[i]);
                            if (regexError) {{
                                return {{ ok: false, value: raw, message: 'Invalid regex "' + patterns[i] + '": ' + regexError }};
                            }}
                        }}
                        return {{ ok: true, value: raw, message: '' }};
                    }}

                    function validateBinaryValue_{widget_id}(raw) {{
                        if (!raw) {{
                            return {{ ok: true, value: raw, message: '' }};
                        }}

                        if (/['"`]/.test(raw)) {{
                            return {{ ok: false, value: raw, message: 'Binary paths cannot contain quotes' }};
                        }}

                        if (/[;&|<>$(){{}}\\[\\]!]/.test(raw)) {{
                            return {{ ok: false, value: raw, message: 'Binary paths can only be a binary name or absolute path' }};
                        }}

                        if (raw.startsWith('/')) {{
                            if (/^[A-Za-z0-9_./+\\- ]+$/.test(raw)) {{
                                return {{ ok: true, value: raw, message: '' }};
                            }}
                            return {{ ok: false, value: raw, message: 'Absolute paths may only contain path-safe characters' }};
                        }}

                        if (/^[A-Za-z0-9_.+-]+$/.test(raw)) {{
                            return {{ ok: true, value: raw, message: '' }};
                        }}

                        return {{ ok: false, value: raw, message: 'Enter a binary name like wget or an absolute path like /usr/bin/wget' }};
                    }}

                    function parseValue_{widget_id}(raw) {{
                        try {{
                            if (raw === 'true') return true;
                            if (raw === 'false') return false;
                            if (raw === 'null') return null;
                            if (raw !== '' && !isNaN(raw)) return Number(raw);
                            if ((raw.startsWith('{{') && raw.endsWith('}}')) ||
                                (raw.startsWith('[') && raw.endsWith(']')) ||
                                (raw.startsWith('"') && raw.endsWith('"'))) {{
                                return JSON.parse(raw);
                            }}
                        }} catch (error) {{
                            return raw;
                        }}
                        return raw;
                    }}

                    function sameValue_{widget_id}(left, right) {{
                        return left === right || JSON.stringify(left) === JSON.stringify(right);
                    }}

                    function parseTypedValue_{widget_id}(raw, typeName, meta) {{
                        var numberValue;
                        var parsed;

                        if (typeName && meta && meta.key && isRegexConfigKey_{widget_id}(meta.key)) {{
                            return validateRegexConfig_{widget_id}(meta.key, raw, typeName);
                        }}

                        if (typeName === 'string' && meta && meta.key && meta.key.endsWith('_BINARY')) {{
                            return validateBinaryValue_{widget_id}(raw);
                        }}

                        if (typeName === 'string') {{
                            if (meta.pattern) {{
                                try {{
                                    if (!(new RegExp(meta.pattern)).test(raw)) {{
                                        return {{ ok: false, value: raw, message: 'Must match pattern ' + meta.pattern }};
                                    }}
                                }} catch (error) {{}}
                            }}
                            return {{ ok: true, value: raw, message: '' }};
                        }}

                        if (typeName === 'integer') {{
                            if (!/^-?\\d+$/.test(raw)) {{
                                return {{ ok: false, value: raw, message: 'Must be an integer' }};
                            }}
                            numberValue = Number(raw);
                            if (meta.minimum !== undefined && numberValue < meta.minimum) {{
                                return {{ ok: false, value: numberValue, message: 'Must be at least ' + meta.minimum }};
                            }}
                            if (meta.maximum !== undefined && numberValue > meta.maximum) {{
                                return {{ ok: false, value: numberValue, message: 'Must be at most ' + meta.maximum }};
                            }}
                            return {{ ok: true, value: numberValue, message: '' }};
                        }}

                        if (typeName === 'number') {{
                            if (raw === '' || isNaN(raw)) {{
                                return {{ ok: false, value: raw, message: 'Must be a number' }};
                            }}
                            numberValue = Number(raw);
                            if (meta.minimum !== undefined && numberValue < meta.minimum) {{
                                return {{ ok: false, value: numberValue, message: 'Must be at least ' + meta.minimum }};
                            }}
                            if (meta.maximum !== undefined && numberValue > meta.maximum) {{
                                return {{ ok: false, value: numberValue, message: 'Must be at most ' + meta.maximum }};
                            }}
                            return {{ ok: true, value: numberValue, message: '' }};
                        }}

                        if (typeName === 'boolean') {{
                            var lowered = raw.toLowerCase();
                            if (lowered === 'true' || raw === '1') return {{ ok: true, value: true, message: '' }};
                            if (lowered === 'false' || raw === '0') return {{ ok: true, value: false, message: '' }};
                            return {{ ok: false, value: raw, message: 'Must be true or false' }};
                        }}

                        if (typeName === 'null') {{
                            return raw === 'null'
                                ? {{ ok: true, value: null, message: '' }}
                                : {{ ok: false, value: raw, message: 'Must be null' }};
                        }}

                        if (typeName === 'array' || typeName === 'object') {{
                            try {{
                                parsed = JSON.parse(raw);
                            }} catch (error) {{
                                return {{ ok: false, value: raw, message: 'Must be valid JSON' }};
                            }}

                            if (typeName === 'array' && Array.isArray(parsed)) {{
                                return {{ ok: true, value: parsed, message: '' }};
                            }}
                            if (typeName === 'object' && parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {{
                                return {{ ok: true, value: parsed, message: '' }};
                            }}

                            return {{
                                ok: false,
                                value: parsed,
                                message: typeName === 'array' ? 'Must be a JSON array' : 'Must be a JSON object',
                            }};
                        }}

                        return {{ ok: true, value: parseValue_{widget_id}(raw), message: '' }};
                    }}

                    function validateValueAgainstMeta_{widget_id}(raw, meta) {{
                        if (!meta || raw === '') {{
                            return {{ state: 'neutral', value: raw, message: '' }};
                        }}

                        var enumValues = Array.isArray(meta.enum) ? meta.enum : [];
                        var types = getTypes_{widget_id}(meta);
                        if (!types.length) {{
                            types = ['string'];
                        }}

                        var error = 'Invalid value';
                        for (var i = 0; i < types.length; i++) {{
                            var candidate = parseTypedValue_{widget_id}(raw, types[i], meta);
                            if (!candidate.ok) {{
                                error = candidate.message || error;
                                continue;
                            }}
                            if (enumValues.length && !enumValues.some(function(enumValue) {{
                                return sameValue_{widget_id}(enumValue, candidate.value) || stringifyValue_{widget_id}(enumValue) === raw;
                            }})) {{
                                error = 'Must be one of: ' + enumValues.map(stringifyValue_{widget_id}).join(', ');
                                continue;
                            }}
                            return {{ state: 'valid', value: candidate.value, message: '' }};
                        }}

                        return {{ state: 'invalid', value: raw, message: error }};
                    }}

                    function ensureRowId_{widget_id}(row) {{
                        if (!row.dataset.rowId) {{
                            row.dataset.rowId = String(rowCounter_{widget_id}++);
                        }}
                        return row.dataset.rowId;
                    }}

                    function setRowHelp_{widget_id}(row) {{
                        var keyInput = row.querySelector('.kv-key');
                        var help = row.querySelector('.kv-help');
                        if (!keyInput || !help) {{
                            return;
                        }}

                        var key = keyInput.value.trim();
                        if (!key) {{
                            help.textContent = '';
                            return;
                        }}

                        var meta = getMetaForKey_{widget_id}(key);
                        if (meta) {{
                            var extra = isRegexConfigKey_{widget_id}(key)
                                ? ((meta.type === 'object' || (Array.isArray(meta.type) && meta.type.includes('object')))
                                    ? ' Expected: JSON object with regex keys.'
                                    : ' Expected: valid regex.')
                                : '';
                            var example = getExampleInput_{widget_id}(key, meta);
                            help.textContent = [describeMeta_{widget_id}(meta) + extra, example].filter(Boolean).join(' ');
                        }} else {{
                            help.textContent = 'Custom key';
                        }}
                    }}

                    function configureValueInput_{widget_id}(row) {{
                        var keyInput = row.querySelector('.kv-key');
                        var valueInput = row.querySelector('.kv-value');
                        var datalist = row.querySelector('.kv-value-options');
                        if (!keyInput || !valueInput || !datalist) {{
                            return;
                        }}

                        var rowId = ensureRowId_{widget_id}(row);
                        datalist.id = '{widget_id}_value_options_' + rowId;

                        var meta = getMetaForKey_{widget_id}(keyInput.value.trim());
                        var enumValues = Array.isArray(meta && meta.enum) ? meta.enum : [];
                        var types = getTypes_{widget_id}(meta);
                        if (!enumValues.length && types.includes('boolean')) {{
                            enumValues = ['True', 'False'];
                        }}
                        if (enumValues.length) {{
                            datalist.innerHTML = enumValues.map(function(enumValue) {{
                                return '<option value="' + stringifyValue_{widget_id}(enumValue).replace(/"/g, '&quot;') + '"></option>';
                            }}).join('');
                            valueInput.setAttribute('list', datalist.id);
                        }} else {{
                            datalist.innerHTML = '';
                            valueInput.removeAttribute('list');
                        }}
                    }}

                    function setValueValidationState_{widget_id}(input, state, message) {{
                        if (!input) {{
                            return;
                        }}

                        if (state === 'valid') {{
                            input.style.borderColor = '#2da44e';
                            input.style.boxShadow = '0 0 0 1px rgba(45, 164, 78, 0.18)';
                            input.style.backgroundColor = '#f6ffed';
                        }} else if (state === 'invalid') {{
                            input.style.borderColor = '#cf222e';
                            input.style.boxShadow = '0 0 0 1px rgba(207, 34, 46, 0.18)';
                            input.style.backgroundColor = '#fff8f8';
                        }} else {{
                            input.style.borderColor = '#ccc';
                            input.style.boxShadow = 'none';
                            input.style.backgroundColor = '';
                        }}
                        input.title = message || '';
                    }}

                    function applyValueValidation_{widget_id}(row) {{
                        var keyInput = row.querySelector('.kv-key');
                        var valueInput = row.querySelector('.kv-value');
                        if (!keyInput || !valueInput) {{
                            return;
                        }}

                        var key = keyInput.value.trim();
                        if (!key) {{
                            setValueValidationState_{widget_id}(valueInput, 'neutral', '');
                            return;
                        }}

                        var meta = getMetaForKey_{widget_id}(key);
                        if (!meta) {{
                            setValueValidationState_{widget_id}(valueInput, 'neutral', '');
                            return;
                        }}

                        var validation = validateValueAgainstMeta_{widget_id}(valueInput.value.trim(), meta);
                        setValueValidationState_{widget_id}(valueInput, validation.state, validation.message);
                    }}

                    function coerceValueForStorage_{widget_id}(key, raw) {{
                        var meta = getMetaForKey_{widget_id}(key);
                        if (!meta) {{
                            return parseValue_{widget_id}(raw);
                        }}

                        var validation = validateValueAgainstMeta_{widget_id}(raw, meta);
                        return validation.state === 'valid' ? validation.value : raw;
                    }}

                    function initializeRows_{widget_id}() {{
                        var container = document.getElementById('{widget_id}_rows');
                        container.querySelectorAll('.key-value-row').forEach(function(row) {{
                            ensureRowId_{widget_id}(row);
                            configureValueInput_{widget_id}(row);
                            setRowHelp_{widget_id}(row);
                            applyValueValidation_{widget_id}(row);
                        }});
                    }}

                    function updateHiddenField_{widget_id}() {{
                        var container = document.getElementById('{widget_id}_rows');
                        var rows = container.querySelectorAll('.key-value-row');
                        var result = {{}};
                        rows.forEach(function(row) {{
                            var keyInput = row.querySelector('.kv-key');
                            var valInput = row.querySelector('.kv-value');
                            if (keyInput && valInput && keyInput.value.trim()) {{
                                var key = keyInput.value.trim();
                                var val = valInput.value.trim();
                                result[key] = coerceValueForStorage_{widget_id}(key, val);
                            }}
                        }});
                        document.getElementById('{widget_id}').value = JSON.stringify(result);
                    }}

                    window.addKeyValueRow_{widget_id} = function() {{
                        var container = document.getElementById('{widget_id}_rows');
                        var newRow = document.createElement('div');
                        newRow.className = 'key-value-row';
                        newRow.style.cssText = 'margin-bottom: 6px;';
                        newRow.innerHTML = '<div class="kv-inputs" style="display: flex; gap: 8px; align-items: center;">' +
                            '<input type="text" class="kv-key" placeholder="KEY" list="{widget_id}_keys" ' +
                            'style="flex: 1; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 12px;">' +
                            '<input type="text" class="kv-value" placeholder="value" ' +
                            'style="flex: 2; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 12px;">' +
                            '<datalist class="kv-value-options"></datalist>' +
                            '<button type="button" onclick="removeKeyValueRow_{widget_id}(this)" ' +
                            'style="padding: 4px 10px; cursor: pointer; background: #ba2121; color: white; border: none; border-radius: 4px; font-weight: bold;">−</button>' +
                            '</div>' +
                            '<div class="kv-help" style="margin-top: 4px; font-size: 11px; color: #666; font-style: italic;"></div>';
                        container.appendChild(newRow);
                        ensureRowId_{widget_id}(newRow);
                        configureValueInput_{widget_id}(newRow);
                        setRowHelp_{widget_id}(newRow);
                        applyValueValidation_{widget_id}(newRow);
                        updateHiddenField_{widget_id}();
                        newRow.querySelector('.kv-key').focus();
                    }};

                    window.removeKeyValueRow_{widget_id} = function(btn) {{
                        var row = btn.closest('.key-value-row');
                        row.remove();
                        updateHiddenField_{widget_id}();
                    }};

                    window.updateHiddenField_{widget_id} = updateHiddenField_{widget_id};

                    function configRowForKey_{widget_id}(key) {{
                        var container = document.getElementById('{widget_id}_rows');
                        if (!container) {{
                            return null;
                        }}
                        var match = null;
                        container.querySelectorAll('.key-value-row').forEach(function(row) {{
                            if (match) {{ return; }}
                            var keyInput = row.querySelector('.kv-key');
                            if (keyInput && keyInput.value.trim() === key) {{
                                match = row;
                            }}
                        }});
                        if (!match) {{
                            window.addKeyValueRow_{widget_id}();
                            var rows = container.querySelectorAll('.key-value-row');
                            match = rows[rows.length - 1];
                            var keyInput = match.querySelector('.kv-key');
                            if (keyInput) {{
                                keyInput.value = key;
                                keyInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            }}
                        }}
                        return match;
                    }}

                    function prefillConfigFromQuery_{widget_id}() {{
                        var params = new URLSearchParams(window.location.search);
                        var consumedConfigKeys = [];
                        params.forEach(function(value, key) {{
                            if (!/^[A-Z][A-Z0-9_]*$/.test(key) || !configMeta_{widget_id}[key]) {{
                                return;
                            }}
                            consumedConfigKeys.push(key);
                            var match = configRowForKey_{widget_id}(key);
                            var valueInput = match && match.querySelector('.kv-value');
                            if (valueInput) {{
                                valueInput.value = value;
                                valueInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            }}
                        }});
                        updateHiddenField_{widget_id}();
                        if (consumedConfigKeys.length) {{
                            var cleanUrl = new URL(window.location.href);
                            consumedConfigKeys.forEach(function(key) {{ cleanUrl.searchParams.delete(key); }});
                            window.history.replaceState(null, '', cleanUrl.pathname + cleanUrl.search + cleanUrl.hash);
                        }}
                    }}

                    function focusConfigKeyFromHash_{widget_id}() {{
                        // Deep-link affordance: ``…/change/#SOME_KEY`` jumps directly
                        // to (or creates) the matching row in this editor. Used by
                        // the setup wizard and live-config detail pages.
                        var hash = (window.location.hash || '').replace(/^#/, '').trim();
                        if (!hash || !/^[A-Z][A-Z0-9_]*$/.test(hash)) {{
                            return;
                        }}
                        var match = configRowForKey_{widget_id}(hash);
                        if (!match) {{
                            return;
                        }}
                        match.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                        var prevOutline = match.style.outline;
                        match.style.outline = '2px solid #f59e0b';
                        match.style.outlineOffset = '2px';
                        match.style.transition = 'outline 1.2s ease-out';
                        setTimeout(function() {{
                            match.style.outline = prevOutline || 'none';
                        }}, 1400);
                        var valueInput = match.querySelector('.kv-value');
                        if (valueInput) {{
                            valueInput.focus();
                            try {{ valueInput.setSelectionRange(valueInput.value.length, valueInput.value.length); }} catch (e) {{}}
                        }}
                    }}

                    // Initialize on load
                    document.addEventListener('DOMContentLoaded', function() {{
                        initializeRows_{widget_id}();
                        prefillConfigFromQuery_{widget_id}();
                        updateHiddenField_{widget_id}();
                        focusConfigKeyFromHash_{widget_id}();
                    }});
                    // Also run immediately in case DOM is already ready
                    if (document.readyState !== 'loading') {{
                        initializeRows_{widget_id}();
                        prefillConfigFromQuery_{widget_id}();
                        updateHiddenField_{widget_id}();
                        focusConfigKeyFromHash_{widget_id}();
                    }}

                    window.addEventListener('hashchange', focusConfigKeyFromHash_{widget_id});

                    // Update on any input change
                    var rowsEl_{widget_id} = document.getElementById('{widget_id}_rows');

                    rowsEl_{widget_id}.addEventListener('input', function(event) {{
                        var row = event.target.closest('.key-value-row');
                        if (!row) {{
                            return;
                        }}

                        if (event.target.classList.contains('kv-key')) {{
                            configureValueInput_{widget_id}(row);
                            setRowHelp_{widget_id}(row);
                        }}

                        if (event.target.classList.contains('kv-key') || event.target.classList.contains('kv-value')) {{
                            applyValueValidation_{widget_id}(row);
                            updateHiddenField_{widget_id}();
                        }}
                    }});
                }})();
            </script>
        </div>
        '''
        return mark_safe(html)

    def _render_row(self, widget_id: str, key: str, value: str) -> str:
        from archivebox.config.common import is_sensitive_config_key

        # Sensitive keys (``*TOKEN*``, ``*SECRET*``, ``*API_KEY*``, ``*APIKEY*``) are
        # rendered write-only: the input is a password field with a placeholder
        # showing the value is set, but the raw value is NEVER sent to the browser.
        # When the user submits the form with the field left blank, the
        # ``ConfigEditorMixin.save_model`` hook re-merges the previously-saved
        # value so leaving it untouched is a no-op rather than a destructive clear.
        is_sensitive = is_sensitive_config_key(key)
        has_value = bool(value)
        if is_sensitive:
            input_type = "password"
            rendered_value = ""
            placeholder = (
                "•••••• (saved — enter new value to replace, clear by deleting row)" if has_value else "value (will be saved write-only)"
            )
            extra_attrs = ' autocomplete="off" data-sensitive="1"' + (' data-had-value="1"' if has_value else "")
        else:
            input_type = "text"
            rendered_value = self._escape(value)
            placeholder = "value"
            extra_attrs = ""
        return f'''
            <div class="key-value-row" style="margin-bottom: 6px;">
                <div class="kv-inputs" style="display: flex; gap: 8px; align-items: center;">
                    <input type="text" class="kv-key" value="{self._escape(key)}" placeholder="KEY" list="{widget_id}_keys"
                           style="flex: 1; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 12px;">
                    <input type="{input_type}" class="kv-value" value="{rendered_value}" placeholder="{self._escape(placeholder)}"{extra_attrs}
                           style="flex: 2; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 12px;">
                    <datalist class="kv-value-options"></datalist>
                    <button type="button" onclick="removeKeyValueRow_{widget_id}(this)"
                            style="padding: 4px 10px; cursor: pointer; background: #ba2121; color: white; border: none; border-radius: 4px; font-weight: bold;">−</button>
                </div>
                <div class="kv-help" style="margin-top: 4px; font-size: 11px; color: #666; font-style: italic;"></div>
            </div>
        '''

    def _escape(self, s: object) -> str:
        """Escape HTML special chars in attribute values."""
        if not s:
            return ""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def value_from_datadict(
        self,
        data: QueryDict | Mapping[str, object],
        files: object,
        name: str,
    ) -> str:
        value = data.get(name, "{}")
        return value if isinstance(value, str) else "{}"


class ConfigEditorMixin(admin.ModelAdmin):
    """
    Mixin for admin classes with a config JSON field.

    Provides a key-value editor widget with autocomplete for available config keys.
    """

    def formfield_for_dbfield(
        self,
        db_field: models.Field,
        request: HttpRequest,
        **kwargs: object,
    ) -> forms.Field | None:
        """Use KeyValueWidget for the config JSON field."""
        if db_field.name == "config":
            kwargs["widget"] = KeyValueWidget()
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def save_model(self, request: HttpRequest, obj, form, change):
        """Preserve write-only redacted credentials on save.

        The KeyValueWidget renders sensitive keys (``*TOKEN*``, ``*SECRET*``,
        ``*API_KEY*``, ``*APIKEY*``) with an empty value + password input —
        the real value never leaves the server. On submit, an empty value
        for a sensitive key that was previously set means "leave untouched",
        not "clear it." We honor that here by re-merging the stored value
        before the row is written. Explicitly removing the row in the UI
        still clears it (the key is gone from the submitted JSON, so there's
        nothing to merge over).
        """
        from archivebox.config.common import is_sensitive_config_key

        if change and obj.pk and obj.config is not None:
            try:
                stored = type(obj).objects.filter(pk=obj.pk).values_list("config", flat=True).first() or {}
            except (AttributeError, DatabaseError, TypeError, ValueError):
                stored = {}
            if isinstance(stored, dict):
                new_config = dict(obj.config or {})
                for key, new_value in list(new_config.items()):
                    if not is_sensitive_config_key(key):
                        continue
                    if new_value not in (None, "") and new_value != "********":
                        continue
                    if key in stored:
                        new_config[key] = stored[key]
                obj.config = new_config
        super().save_model(request, obj, form, change)


class BaseModelAdmin(DjangoObjectActions, admin.ModelAdmin):
    list_display = ("id", "created_at", "created_by")
    readonly_fields = ("id", "created_at", "modified_at")
    show_search_mode_selector = False
    change_form_template = "admin/archivebox_change_form.html"

    def get_admin_toolbar_actions(self, request, obj):
        """Return extra action button dicts for the shared change-form toolbar.

        See ``templates/admin/includes/archivebox_toolbar.html`` for the
        accepted keys. Default: no extras (toolbar renders Save/History/Delete
        plus any ``django-object-actions`` change_actions).
        """
        return []

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        context.setdefault("archivebox_admin_actions", self.get_admin_toolbar_actions(request, obj))
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def get_default_search_mode(self) -> str:
        # The shared changelist template always asks every admin for a default
        # search mode, even when the search-mode toggle is hidden.
        return "meta"

    def get_form(
        self,
        request: HttpRequest,
        obj: models.Model | None = None,
        change: bool = False,
        **kwargs: object,
    ):
        form = super().get_form(request, obj, change=change, **kwargs)
        if "created_by" in form.base_fields:
            form.base_fields["created_by"].initial = request.user
        return form

    def get_urls(self):
        """Swap the per-object admin URLs from ``<path:object_id>`` to
        ``<hexuuid:object_id>`` so canonical change/delete/history URLs use the
        32-char hex form. The hyphenated form still resolves because the
        converter's regex accepts both — Django reverses through ``to_url``
        which always emits hex, so links in templates / changelists / inline
        formsets all canonicalize automatically.

        Non-UUID PKs (an ``IntegerField`` PK on some legacy table, for example)
        won't match the converter's regex and fall back to the default
        ``<path:object_id>`` patterns we still include after our swap.
        """
        info = self.opts.app_label, self.opts.model_name
        object_routes = [
            path("<hexuuid:object_id>/history/", self.admin_site.admin_view(self.history_view), name="{}_{}_history".format(*info)),
            path("<hexuuid:object_id>/delete/", self.admin_site.admin_view(self.delete_view), name="{}_{}_delete".format(*info)),
            path("<hexuuid:object_id>/change/", self.admin_site.admin_view(self.change_view), name="{}_{}_change".format(*info)),
        ]
        # Append after super().get_urls() so our patterns are the
        # *last-registered* ones with the canonical admin URL names — Django's
        # reverse() picks the later registration when names collide, which is
        # how we make ``reverse("admin:app_model_change", args=[obj.pk])``
        # emit the hex form. The original ``<path:object_id>`` routes stay in
        # place as a fallback for non-UUID PKs and for resolving inbound
        # hyphenated URLs (the ``hexuuid`` regex accepts both forms anyway).
        return super().get_urls() + object_routes
