"""Base admin classes for models using UUIDv7."""

__package__ = 'archivebox.base_models'

import json
from collections.abc import Mapping
from typing import NotRequired, TypedDict

from django import forms
from django.contrib import admin
from django.db import models
from django.forms.renderers import BaseRenderer
from django.http import HttpRequest, QueryDict
from django.utils.safestring import SafeString, mark_safe
from django_object_actions import DjangoObjectActions


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
        css = {
            'all': []
        }
        js = []

    def _get_config_options(self) -> dict[str, ConfigOption]:
        """Get available config options from plugins."""
        try:
            from archivebox.hooks import discover_plugin_configs
            plugin_configs = discover_plugin_configs()
            options: dict[str, ConfigOption] = {}
            for plugin_name, schema in plugin_configs.items():
                for key, prop in schema.get('properties', {}).items():
                    option: ConfigOption = {
                        'plugin': plugin_name,
                        'type': prop.get('type', 'string'),
                        'default': prop.get('default', ''),
                        'description': prop.get('description', ''),
                    }
                    for schema_key in ('enum', 'pattern', 'minimum', 'maximum'):
                        if schema_key in prop:
                            option[schema_key] = prop[schema_key]
                    options[key] = option
            return options
        except Exception:
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

        widget_id = attrs.get('id', name) if attrs else name
        config_options = self._get_config_options()

        # Build datalist options
        datalist_options = '\n'.join(
            f'<option value="{self._escape(key)}">{self._escape(opt["description"][:60] or opt["type"])}</option>'
            for key, opt in sorted(config_options.items())
        )

        # Build config metadata as JSON for JS
        config_meta_json = json.dumps(config_options)

        html = f'''
        <div id="{widget_id}_container" class="key-value-editor" style="max-width: 700px;">
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
        html += self._render_row(widget_id, '', '')

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
                            if (key === 'SAVE_ALLOWLIST' || key === 'SAVE_DENYLIST') {{
                                return 'Example: {{"^https://example\\\\.com": ["wget"]}}';
                            }}
                            return 'Example: {{"key": "value"}}';
                        }}
                        return '';
                    }}

                    function isRegexConfigKey_{widget_id}(key) {{
                        return key === 'URL_ALLOWLIST' ||
                            key === 'URL_DENYLIST' ||
                            key === 'SAVE_ALLOWLIST' ||
                            key === 'SAVE_DENYLIST' ||
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
                        newRow.innerHTML = '<div style="display: flex; gap: 8px; align-items: center;">' +
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

                    // Initialize on load
                    document.addEventListener('DOMContentLoaded', function() {{
                        initializeRows_{widget_id}();
                        updateHiddenField_{widget_id}();
                    }});
                    // Also run immediately in case DOM is already ready
                    if (document.readyState !== 'loading') {{
                        initializeRows_{widget_id}();
                        updateHiddenField_{widget_id}();
                    }}

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
        return f'''
            <div class="key-value-row" style="margin-bottom: 6px;">
                <div style="display: flex; gap: 8px; align-items: center;">
                    <input type="text" class="kv-key" value="{self._escape(key)}" placeholder="KEY" list="{widget_id}_keys"
                           style="flex: 1; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 12px;">
                    <input type="text" class="kv-value" value="{self._escape(value)}" placeholder="value"
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
            return ''
        return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

    def value_from_datadict(
        self,
        data: QueryDict | Mapping[str, object],
        files: object,
        name: str,
    ) -> str:
        value = data.get(name, '{}')
        return value if isinstance(value, str) else '{}'


class ConfigEditorMixin(admin.ModelAdmin):
    """
    Mixin for admin classes with a config JSON field.

    Provides a key-value editor widget with autocomplete for available config keys.
    """

    def formfield_for_dbfield(
        self,
        db_field: models.Field[object, object],
        request: HttpRequest,
        **kwargs: object,
    ) -> forms.Field | None:
        """Use KeyValueWidget for the config JSON field."""
        if db_field.name == 'config':
            kwargs['widget'] = KeyValueWidget()
        return super().formfield_for_dbfield(db_field, request, **kwargs)


class BaseModelAdmin(DjangoObjectActions, admin.ModelAdmin):
    list_display = ('id', 'created_at', 'created_by')
    readonly_fields = ('id', 'created_at', 'modified_at')

    def get_form(
        self,
        request: HttpRequest,
        obj: models.Model | None = None,
        change: bool = False,
        **kwargs: object,
    ):
        form = super().get_form(request, obj, change=change, **kwargs)
        if 'created_by' in form.base_fields:
            form.base_fields['created_by'].initial = request.user
        return form
