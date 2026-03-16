"""Base admin classes for models using UUIDv7."""

__package__ = 'archivebox.base_models'

import json
from collections.abc import Mapping
from typing import TypedDict

from django import forms
from django.contrib import admin
from django.db import models
from django.forms.renderers import BaseRenderer
from django.http import HttpRequest, QueryDict
from django.utils.safestring import SafeString, mark_safe
from django_object_actions import DjangoObjectActions


class ConfigOption(TypedDict):
    plugin: str
    type: str
    default: object
    description: str


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
                    options[key] = {
                        'plugin': plugin_name,
                        'type': prop.get('type', 'string'),
                        'default': prop.get('default', ''),
                        'description': prop.get('description', ''),
                    }
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
        row_idx = 0
        for key, val in data.items():
            val_str = json.dumps(val) if not isinstance(val, str) else val
            html += self._render_row(widget_id, row_idx, key, val_str)
            row_idx += 1

        # Always add one empty row for new entries
        html += self._render_row(widget_id, row_idx, '', '')

        html += f'''
            </div>
            <div style="display: flex; gap: 8px; align-items: center; margin-top: 8px;">
                <button type="button" onclick="addKeyValueRow_{widget_id}()"
                        style="padding: 4px 12px; cursor: pointer; background: #417690; color: white; border: none; border-radius: 4px;">
                    + Add Row
                </button>
                <span id="{widget_id}_hint" style="font-size: 11px; color: #666; font-style: italic;"></span>
            </div>
            <input type="hidden" name="{name}" id="{widget_id}" value="">
            <script>
                (function() {{
                    var configMeta_{widget_id} = {config_meta_json};

                    function showKeyHint_{widget_id}(key) {{
                        var hint = document.getElementById('{widget_id}_hint');
                        var meta = configMeta_{widget_id}[key];
                        if (meta) {{
                            hint.innerHTML = '<b>' + key + '</b>: ' + (meta.description || meta.type) +
                                (meta.default !== '' ? ' <span style="color:#888">(default: ' + meta.default + ')</span>' : '');
                        }} else {{
                            hint.textContent = key ? 'Custom key: ' + key : '';
                        }}
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
                                // Try to parse as JSON (for booleans, numbers, etc)
                                try {{
                                    if (val === 'true') result[key] = true;
                                    else if (val === 'false') result[key] = false;
                                    else if (val === 'null') result[key] = null;
                                    else if (!isNaN(val) && val !== '') result[key] = Number(val);
                                    else if ((val.startsWith('{{') && val.endsWith('}}')) ||
                                             (val.startsWith('[') && val.endsWith(']')) ||
                                             (val.startsWith('"') && val.endsWith('"')))
                                        result[key] = JSON.parse(val);
                                    else result[key] = val;
                                }} catch(e) {{
                                    result[key] = val;
                                }}
                            }}
                        }});
                        document.getElementById('{widget_id}').value = JSON.stringify(result);
                    }}

                    window.addKeyValueRow_{widget_id} = function() {{
                        var container = document.getElementById('{widget_id}_rows');
                        var rows = container.querySelectorAll('.key-value-row');
                        var newIdx = rows.length;
                        var newRow = document.createElement('div');
                        newRow.className = 'key-value-row';
                        newRow.style.cssText = 'display: flex; gap: 8px; margin-bottom: 6px; align-items: center;';
                        newRow.innerHTML = '<input type="text" class="kv-key" placeholder="KEY" list="{widget_id}_keys" ' +
                            'style="flex: 1; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 12px;" ' +
                            'onchange="updateHiddenField_{widget_id}()" oninput="updateHiddenField_{widget_id}(); showKeyHint_{widget_id}(this.value)" onfocus="showKeyHint_{widget_id}(this.value)">' +
                            '<input type="text" class="kv-value" placeholder="value" ' +
                            'style="flex: 2; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 12px;" ' +
                            'onchange="updateHiddenField_{widget_id}()" oninput="updateHiddenField_{widget_id}()">' +
                            '<button type="button" onclick="removeKeyValueRow_{widget_id}(this)" ' +
                            'style="padding: 4px 10px; cursor: pointer; background: #ba2121; color: white; border: none; border-radius: 4px; font-weight: bold;">−</button>';
                        container.appendChild(newRow);
                        newRow.querySelector('.kv-key').focus();
                    }};

                    window.removeKeyValueRow_{widget_id} = function(btn) {{
                        var row = btn.parentElement;
                        row.remove();
                        updateHiddenField_{widget_id}();
                    }};

                    window.showKeyHint_{widget_id} = showKeyHint_{widget_id};
                    window.updateHiddenField_{widget_id} = updateHiddenField_{widget_id};

                    // Initialize on load
                    document.addEventListener('DOMContentLoaded', function() {{
                        updateHiddenField_{widget_id}();
                    }});
                    // Also run immediately in case DOM is already ready
                    if (document.readyState !== 'loading') {{
                        updateHiddenField_{widget_id}();
                    }}

                    // Update on any input change
                    document.getElementById('{widget_id}_rows').addEventListener('input', updateHiddenField_{widget_id});
                }})();
            </script>
        </div>
        '''
        return mark_safe(html)

    def _render_row(self, widget_id: str, idx: int, key: str, value: str) -> str:
        return f'''
            <div class="key-value-row" style="display: flex; gap: 8px; margin-bottom: 6px; align-items: center;">
                <input type="text" class="kv-key" value="{self._escape(key)}" placeholder="KEY" list="{widget_id}_keys"
                       style="flex: 1; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 12px;"
                       onchange="updateHiddenField_{widget_id}()" oninput="updateHiddenField_{widget_id}(); showKeyHint_{widget_id}(this.value)" onfocus="showKeyHint_{widget_id}(this.value)">
                <input type="text" class="kv-value" value="{self._escape(value)}" placeholder="value"
                       style="flex: 2; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 12px;"
                       onchange="updateHiddenField_{widget_id}()" oninput="updateHiddenField_{widget_id}()">
                <button type="button" onclick="removeKeyValueRow_{widget_id}(this)"
                        style="padding: 4px 10px; cursor: pointer; background: #ba2121; color: white; border: none; border-radius: 4px; font-weight: bold;">−</button>
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
