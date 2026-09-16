__package__ = "archivebox.core"

import json
import re
import hashlib
from django import forms
from django.db.models.manager import BaseManager
from django.db.models.query import QuerySet
from django.template.loader import render_to_string
from django.utils.html import escape
from django.utils.safestring import mark_safe


class TagEditorWidget(forms.Widget):
    """
    A widget that renders tags as clickable pills with inline editing.
    - Displays existing tags alphabetically as styled pills with X remove button
    - Text input with HTML5 datalist for autocomplete suggestions
    - Press Enter or Space to create new tags (auto-creates if doesn't exist)
    - Uses AJAX for autocomplete and tag creation
    """

    template_name = "admin/widgets/tags.html"

    def __init__(self, attrs=None, snapshot_id=None):
        self.snapshot_id = snapshot_id
        super().__init__(attrs)

    def _escape(self, value):
        """Escape HTML entities in value."""
        return escape(str(value)) if value else ""

    def _normalize_id(self, value):
        """Normalize IDs for HTML + JS usage (letters, digits, underscore; JS-safe start)."""
        normalized = re.sub(r"[^A-Za-z0-9_]", "_", str(value))
        if not normalized or not re.match(r"[A-Za-z_]", normalized):
            normalized = f"t_{normalized}"
        return normalized

    def _tag_style(self, value):
        """Compute a stable pastel color style for a tag value."""
        tag = (value or "").strip().lower()
        digest = hashlib.md5(tag.encode("utf-8")).hexdigest()
        hue = int(digest[:4], 16) % 360
        bg = f"hsl({hue}, 70%, 92%)"
        border = f"hsl({hue}, 60%, 82%)"
        fg = f"hsl({hue}, 35%, 28%)"
        return f"--tag-bg: {bg}; --tag-border: {border}; --tag-fg: {fg};"

    def render(self, name, value, attrs=None, renderer=None):
        """
        Render the tag editor widget.

        Args:
            name: Field name
            value: Can be:
                - QuerySet of Tag objects (from M2M field)
                - List of tag names
                - Comma-separated string of tag names
                - None
            attrs: HTML attributes
            renderer: Not used
        """
        # Parse value to get list of tag names
        tags = []
        if value:
            if isinstance(value, (BaseManager, QuerySet)):
                tags = sorted([tag.name for tag in value.all()])
            elif isinstance(value, (list, tuple)):
                from archivebox.core.models import Tag

                if value and isinstance(value[0], Tag):  # List of Tag objects
                    tags = sorted([tag.name for tag in value])
                else:  # List of strings or IDs
                    # Could be tag IDs from form submission
                    from archivebox.core.models import Tag

                    tag_names = []
                    for v in value:
                        if isinstance(v, str) and not v.isdigit():
                            tag_names.append(v)
                        else:
                            try:
                                tag = Tag.objects.get(pk=v)
                                tag_names.append(tag.name)
                            except (Tag.DoesNotExist, ValueError):
                                if isinstance(v, str):
                                    tag_names.append(v)
                    tags = sorted(tag_names)
            elif isinstance(value, str):
                tags = sorted([t.strip() for t in value.split(",") if t.strip()])

        widget_id_raw = attrs.get("id", name) if attrs else name
        widget_id = self._normalize_id(widget_id_raw)

        return render_to_string(
            self.template_name,
            {"name": name, "widget_id": widget_id, "tags_id": f"{widget_id}_tags", "tags": tags},
        )


class URLFiltersWidget(forms.Widget):
    """Render URL allowlist / denylist controls with same-domain autofill."""

    template_name = ""

    def __init__(self, attrs=None, *, source_selector='textarea[name="url"]'):
        self.source_selector = source_selector
        super().__init__(attrs)

    def render(self, name, value, attrs=None, renderer=None):
        value = value if isinstance(value, dict) else {}
        widget_id_raw = attrs.get("id", name) if attrs else name
        widget_id = re.sub(r"[^A-Za-z0-9_]", "_", str(widget_id_raw)) or name
        value = value or {}
        allowlist = escape(value.get("allowlist", "") or "")
        denylist = escape(value.get("denylist", "") or "")
        same_domain_checked = " checked" if value.get("same_domain_only") else ""
        subpaths_checked = " checked" if value.get("subpaths_only") else ""
        only_new_checked = " checked" if value.get("only_new") else ""

        return mark_safe(f'''
        <div id="{widget_id}_container" class="url-filters-widget">
            <input type="hidden" name="{name}" value="">
            <div class="url-filters-grid">
                <div class="url-filters-column">
                    <div class="url-filter-label-row">
                        <label for="{widget_id}_allowlist" class="url-filter-label"><span class="url-filter-label-main">🟢 URL_ALLOWLIST</span></label>
                        <span class="url-filter-label-note">Regex patterns or domains to include, one pattern per line.</span>
                    </div>
                    <textarea id="{widget_id}_allowlist"
                              name="{name}_allowlist"
                              rows="2"
                              placeholder="^https?://([^/]+\\.)?(example\\.com|example\\.org)([:/]|$)">{allowlist}</textarea>
                </div>
                <div class="url-filters-column">
                    <div class="url-filter-label-row">
                        <label for="{widget_id}_denylist" class="url-filter-label"><span class="url-filter-label-main">⛔ URL_DENYLIST</span></label>
                        <span class="url-filter-label-note">Regex patterns or domains to exclude, one pattern per line.</span>
                    </div>
                    <textarea id="{widget_id}_denylist"
                              name="{name}_denylist"
                              rows="2"
                              placeholder="^https?://([^/]+\\.)?(cdn\\.example\\.com|analytics\\.example\\.org)([:/]|$)">{denylist}</textarea>
                </div>
            </div>
            <label class="url-filters-toggle" for="{widget_id}_same_domain_only">
                <input type="checkbox" id="{widget_id}_same_domain_only" name="{name}_same_domain_only" value="1"{same_domain_checked}>
                <span>Same domain only</span>
            </label>
            <label class="url-filters-toggle" for="{widget_id}_subpaths_only">
                <input type="checkbox" id="{widget_id}_subpaths_only" name="{name}_subpaths_only" value="1"{subpaths_checked}>
                <span>Subpaths only</span>
            </label>
            <label class="url-filters-toggle url-filters-toggle-with-help" for="{widget_id}_only_new">
                <input type="checkbox" id="{widget_id}_only_new" name="{name}_only_new" value="1"{only_new_checked}>
                <span>Only new URLs</span>
                <small>skip URLs you've previously saved</small>
            </label>
            <div class="help-text">These values can be one regex pattern or domain per line. URL_DENYLIST takes precedence over URL_ALLOWLIST.</div>
            <script>
            (function() {{
                var allowlistField = document.getElementById('{widget_id}_allowlist');
                var denylistField = document.getElementById('{widget_id}_denylist');
                var sameDomainOnly = document.getElementById('{widget_id}_same_domain_only');
                var subpathsOnly = document.getElementById('{widget_id}_subpaths_only');
                var sourceField = document.querySelector({json.dumps(self.source_selector)});
                var lastAutoGeneratedAllowlist = '';
                if (!allowlistField || !sameDomainOnly || !subpathsOnly || !sourceField) {{
                    return;
                }}

                function extractUrl(line) {{
                    var trimmed = String(line || '').trim();
                    if (!trimmed || trimmed.charAt(0) === '#') {{
                        return '';
                    }}
                    if (trimmed.charAt(0) === '{{') {{
                        try {{
                            var record = JSON.parse(trimmed);
                            return String(record.url || '').trim();
                        }} catch (error) {{
                            return '';
                        }}
                    }}
                    return trimmed;
                }}

                function escapeRegex(text) {{
                    return String(text || '').replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&');
                }}

                function buildHostRegex(domains) {{
                    if (!domains.length) {{
                        return '';
                    }}
                    return '^https?://(' + domains.map(escapeRegex).join('|') + ')([:/]|$)';
                }}

                function buildSubpathRegex(paths) {{
                    if (!paths.length) {{
                        return '';
                    }}
                    return paths.map(function(item) {{
                        if (item.path === '/') {{
                            return '^https?://' + escapeRegex(item.host) + '([/?#]|$)';
                        }}
                        if (item.path.endsWith('/')) {{
                            return '^https?://' + escapeRegex(item.host) + escapeRegex(item.path);
                        }}
                        return '^https?://' + escapeRegex(item.host) + escapeRegex(item.path) + '([/?#]|$)';
                    }}).join('\\n');
                }}

                function getSubpathPrefix(parsed) {{
                    var pathname = String(parsed.pathname || '/').replace(/\\/+/g, '/');
                    if (!pathname || pathname === '/') {{
                        return '/';
                    }}
                    if (pathname.endsWith('/')) {{
                        return pathname;
                    }}
                    var lastSlash = pathname.lastIndexOf('/');
                    var lastPart = pathname.slice(lastSlash + 1);
                    if (lastPart.indexOf('.') !== -1) {{
                        return pathname.slice(0, lastSlash + 1) || '/';
                    }}
                    return pathname;
                }}

                function getConfigEditorRows() {{
                    return document.getElementById('id_config_rows');
                }}

                function getConfigUpdater() {{
                    return window.updateHiddenField_id_config || null;
                }}

                function findConfigRow(key) {{
                    var rows = getConfigEditorRows();
                    if (!rows) {{
                        return null;
                    }}
                    var matches = Array.prototype.filter.call(rows.querySelectorAll('.key-value-row'), function(row) {{
                        var keyInput = row.querySelector('.kv-key');
                        return keyInput && keyInput.value.trim() === key;
                    }});
                    return matches.length ? matches[0] : null;
                }}

                function addConfigRow() {{
                    if (typeof window.addKeyValueRow_id_config === 'function') {{
                        window.addKeyValueRow_id_config();
                        var rows = getConfigEditorRows();
                        return rows ? rows.lastElementChild : null;
                    }}
                    return null;
                }}

                function setConfigRow(key, value) {{
                    var rows = getConfigEditorRows();
                    var updater = getConfigUpdater();
                    if (!rows || !updater) {{
                        return;
                    }}

                    var row = findConfigRow(key);
                    if (!value) {{
                        if (row) {{
                            row.remove();
                            updater();
                        }}
                        return;
                    }}

                    if (!row) {{
                        row = addConfigRow();
                    }}
                    if (!row) {{
                        return;
                    }}

                    var keyInput = row.querySelector('.kv-key');
                    var valueInput = row.querySelector('.kv-value');
                    if (!keyInput || !valueInput) {{
                        return;
                    }}

                    keyInput.value = key;
                    valueInput.value = value;
                    keyInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    valueInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    updater();
                }}

                function syncConfigEditor() {{
                    setConfigRow('URL_ALLOWLIST', allowlistField.value.trim());
                    setConfigRow('URL_DENYLIST', denylistField ? denylistField.value.trim() : '');
                }}

                function syncAllowlistFromUrls() {{
                    if (!sameDomainOnly.checked && !subpathsOnly.checked) {{
                        if (allowlistField.value.trim() === lastAutoGeneratedAllowlist) {{
                            allowlistField.value = '';
                            syncConfigEditor();
                        }}
                        lastAutoGeneratedAllowlist = '';
                        return;
                    }}

                    var seen = Object.create(null);
                    var domains = [];
                    var paths = [];
                    sourceField.value.split(/\\n+/).forEach(function(line) {{
                        var url = extractUrl(line);
                        if (!url) {{
                            return;
                        }}
                        try {{
                            var parsed = new URL(url);
                            var domain = String(parsed.hostname || '').toLowerCase();
                            if (!domain || seen[domain]) {{
                                domain = '';
                            }}
                            if (domain) {{
                                seen[domain] = true;
                                domains.push(domain);
                            }}
                            if (subpathsOnly.checked) {{
                                var pathname = getSubpathPrefix(parsed);
                                var hostAndPort = String(parsed.host || parsed.hostname || '').toLowerCase();
                                var pathKey = hostAndPort + pathname;
                                if (!hostAndPort || seen[pathKey]) {{
                                    return;
                                }}
                                seen[pathKey] = true;
                                paths.push({{ host: hostAndPort, path: pathname }});
                            }}
                        }} catch (error) {{
                            return;
                        }}
                    }});
                    lastAutoGeneratedAllowlist = subpathsOnly.checked ? buildSubpathRegex(paths) : buildHostRegex(domains);
                    allowlistField.value = lastAutoGeneratedAllowlist;
                    syncConfigEditor();
                }}

                sameDomainOnly.addEventListener('change', syncAllowlistFromUrls);
                subpathsOnly.addEventListener('change', syncAllowlistFromUrls);
                sourceField.addEventListener('input', syncAllowlistFromUrls);
                sourceField.addEventListener('change', syncAllowlistFromUrls);
                allowlistField.addEventListener('input', syncConfigEditor);
                allowlistField.addEventListener('change', syncConfigEditor);
                if (denylistField) {{
                    denylistField.addEventListener('input', syncConfigEditor);
                    denylistField.addEventListener('change', syncConfigEditor);
                }}

                if (document.readyState === 'loading') {{
                    document.addEventListener('DOMContentLoaded', syncConfigEditor, {{ once: true }});
                }} else {{
                    syncConfigEditor();
                }}
            }})();
            </script>
        </div>
        ''')

    def value_from_datadict(self, data, files, name):
        return {
            "allowlist": data.get(f"{name}_allowlist", ""),
            "denylist": data.get(f"{name}_denylist", ""),
            "same_domain_only": data.get(f"{name}_same_domain_only") in ("1", "on", "true"),
            "subpaths_only": data.get(f"{name}_subpaths_only") in ("1", "on", "true"),
            "only_new": data.get(f"{name}_only_new") in ("1", "on", "true"),
        }


class InlineTagEditorWidget(TagEditorWidget):
    """
    Inline version of TagEditorWidget for use in list views.
    Includes AJAX save functionality for immediate persistence.
    """

    def __init__(self, attrs=None, snapshot_id=None, editable=True):
        super().__init__(attrs, snapshot_id)
        self.snapshot_id = snapshot_id
        self.editable = editable

    def render(self, name, value, attrs=None, renderer=None, snapshot_id=None):
        """Render inline tag editor with AJAX save."""
        # Use snapshot_id from __init__ or from render call
        snapshot_id = snapshot_id or self.snapshot_id

        # Parse value to get list of tag dicts with id and name
        tag_data = []
        if value:
            if isinstance(value, (BaseManager, QuerySet)):
                for tag in value.all():
                    tag_data.append({"id": tag.pk, "name": tag.name})
                tag_data.sort(key=lambda x: x["name"].lower())
            elif isinstance(value, (list, tuple)):
                from archivebox.core.models import Tag

                if value and isinstance(value[0], Tag):
                    for tag in value:
                        tag_data.append({"id": tag.pk, "name": tag.name})
                    tag_data.sort(key=lambda x: x["name"].lower())

        widget_id_raw = f"inline_tags_{snapshot_id}" if snapshot_id else (attrs.get("id", name) if attrs else name)
        widget_id = self._normalize_id(widget_id_raw)

        # Build pills HTML with filter links
        pills_html = ""
        for td in tag_data:
            remove_button = ""
            if self.editable:
                remove_button = (
                    f'<button type="button" class="tag-remove-btn" '
                    f'data-tag-id="{td["id"]}" data-tag-name="{self._escape(td["name"])}">&times;</button>'
                )
            pills_html += f'''
                <span class="tag-pill" data-tag="{self._escape(td["name"])}" data-tag-id="{td["id"]}" style="{self._tag_style(td["name"])}">
                    <a href="/admin/core/snapshot/?tags__id__exact={td["id"]}" class="tag-link">{self._escape(td["name"])}</a>
                    {remove_button}
                </span>
            '''

        tags_json = escape(json.dumps(tag_data))
        input_html = ""
        readonly_class = " readonly" if not self.editable else ""
        if self.editable:
            input_html = f'''
            <input type="text"
                   id="{widget_id}_input"
                   class="tag-inline-input-sm"
                   list="{widget_id}_datalist"
                   placeholder="+"
                   autocomplete="off"
                   data-inline-tag-input="1"
            >
            <datalist id="{widget_id}_datalist"></datalist>
            '''

        html = f'''
        <span id="{widget_id}_container" class="tag-editor-inline{readonly_class}" data-snapshot-id="{snapshot_id}" data-tags="{tags_json}" data-readonly="{int(not self.editable)}">
            <span id="{widget_id}_pills" class="tag-pills-inline">
                {pills_html}
            </span>
            {input_html}
        </span>
        '''

        return mark_safe(html)
