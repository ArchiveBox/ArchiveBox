__package__ = "archivebox.core"

import json
import re
import hashlib
from django import forms
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

    template_name = ""  # We render manually

    class Media:
        css = {"all": []}
        js = []

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
            if hasattr(value, "all"):  # QuerySet
                tags = sorted([tag.name for tag in value.all()])
            elif isinstance(value, (list, tuple)):
                if value and hasattr(value[0], "name"):  # List of Tag objects
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

        # Build pills HTML
        pills_html = ""
        for tag in tags:
            pills_html += f'''
                <span class="tag-pill" data-tag="{self._escape(tag)}" style="{self._tag_style(tag)}">
                    {self._escape(tag)}
                    <button type="button" class="tag-remove-btn" data-tag-name="{self._escape(tag)}">&times;</button>
                </span>
            '''

        # Build the widget HTML
        html = f'''
        <div id="{widget_id}_container" class="tag-editor-container" onclick="focusTagInput_{widget_id}(event)">
            <div id="{widget_id}_pills" class="tag-pills">
                {pills_html}
            </div>
            <input type="text"
                   id="{widget_id}_input"
                   class="tag-inline-input"
                   list="{widget_id}_datalist"
                   placeholder="Add tag..."
                   autocomplete="off"
                   onkeydown="handleTagKeydown_{widget_id}(event)"
                   onkeypress="if(event.key==='Enter' || event.keyCode===13 || event.key===' ' || event.code==='Space' || event.key==='Spacebar'){{event.preventDefault(); event.stopPropagation();}}"
                   oninput="fetchTagAutocomplete_{widget_id}(this.value)"
            >
            <datalist id="{widget_id}_datalist"></datalist>
            <input type="hidden" name="{name}" id="{widget_id}" value="{self._escape(",".join(tags))}">
        </div>

        <script>
        (function() {{
            var currentTags_{widget_id} = {json.dumps(tags)};
            var autocompleteTimeout_{widget_id} = null;

            window.focusTagInput_{widget_id} = function(event) {{
                if (event.target.classList.contains('tag-remove-btn')) return;
                document.getElementById('{widget_id}_input').focus();
            }};

            window.updateHiddenInput_{widget_id} = function() {{
                var hiddenInput = document.getElementById('{widget_id}');
                if (!hiddenInput) {{
                    return;
                }}
                hiddenInput.value = currentTags_{widget_id}.join(',');
                hiddenInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                hiddenInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }};

            function normalizeTags_{widget_id}(value) {{
                var rawTags = Array.isArray(value) ? value : String(value || '').split(',');
                var seen = {{}};
                return rawTags
                    .map(function(tag) {{ return String(tag || '').trim(); }})
                    .filter(function(tag) {{
                        if (!tag) return false;
                        var normalized = tag.toLowerCase();
                        if (seen[normalized]) return false;
                        seen[normalized] = true;
                        return true;
                    }})
                    .sort(function(a, b) {{
                        return a.toLowerCase().localeCompare(b.toLowerCase());
                    }});
            }}

            window.setTags_{widget_id} = function(value, options) {{
                currentTags_{widget_id} = normalizeTags_{widget_id}(value);
                rebuildPills_{widget_id}();
                if (!(options && options.skipHiddenUpdate)) {{
                    updateHiddenInput_{widget_id}();
                }}
            }};

            window.syncTagEditorFromHidden_{widget_id} = function() {{
                var hiddenInput = document.getElementById('{widget_id}');
                if (!hiddenInput) {{
                    return;
                }}
                setTags_{widget_id}(hiddenInput.value, {{ skipHiddenUpdate: true }});
            }};

            function computeTagStyle_{widget_id}(tagName) {{
                var hash = 0;
                var name = String(tagName || '').toLowerCase();
                for (var i = 0; i < name.length; i++) {{
                    hash = (hash * 31 + name.charCodeAt(i)) % 360;
                }}
                var bg = 'hsl(' + hash + ', 70%, 92%)';
                var border = 'hsl(' + hash + ', 60%, 82%)';
                var fg = 'hsl(' + hash + ', 35%, 28%)';
                return {{ bg: bg, border: border, fg: fg }};
            }}

            function applyTagStyle_{widget_id}(el, tagName) {{
                var colors = computeTagStyle_{widget_id}(tagName);
                el.style.setProperty('--tag-bg', colors.bg);
                el.style.setProperty('--tag-border', colors.border);
                el.style.setProperty('--tag-fg', colors.fg);
            }}

            function getApiKey() {{
                return (window.ARCHIVEBOX_API_KEY || '').trim();
            }}

            function buildApiUrl(path) {{
                var apiKey = getApiKey();
                if (!apiKey) return path;
                var sep = path.indexOf('?') !== -1 ? '&' : '?';
                return path + sep + 'api_key=' + encodeURIComponent(apiKey);
            }}

            function buildApiHeaders() {{
                var headers = {{
                    'Content-Type': 'application/json',
                }};
                var apiKey = getApiKey();
                if (apiKey) headers['X-ArchiveBox-API-Key'] = apiKey;
                var csrfToken = getCSRFToken();
                if (csrfToken) headers['X-CSRFToken'] = csrfToken;
                return headers;
            }}

            window.addTag_{widget_id} = function(tagName) {{
                tagName = tagName.trim();
                if (!tagName) return;

                // Check if tag already exists (case-insensitive)
                var exists = currentTags_{widget_id}.some(function(t) {{
                    return t.toLowerCase() === tagName.toLowerCase();
                }});
                if (exists) {{
                    document.getElementById('{widget_id}_input').value = '';
                    return;
                }}

                // Add to current tags
                currentTags_{widget_id}.push(tagName);
                currentTags_{widget_id} = normalizeTags_{widget_id}(currentTags_{widget_id});

                // Rebuild pills
                rebuildPills_{widget_id}();
                updateHiddenInput_{widget_id}();

                // Clear input
                document.getElementById('{widget_id}_input').value = '';

                // Create tag via API if it doesn't exist (fire and forget)
                fetch(buildApiUrl('/api/v1/core/tags/create/'), {{
                    method: 'POST',
                    headers: buildApiHeaders(),
                    body: JSON.stringify({{ name: tagName }})
                }}).catch(function(err) {{
                    console.log('Tag creation note:', err);
                }});
            }};

            window.removeTag_{widget_id} = function(tagName) {{
                currentTags_{widget_id} = currentTags_{widget_id}.filter(function(t) {{
                    return t.toLowerCase() !== tagName.toLowerCase();
                }});
                rebuildPills_{widget_id}();
                updateHiddenInput_{widget_id}();
            }};

            window.rebuildPills_{widget_id} = function() {{
                var container = document.getElementById('{widget_id}_pills');
                container.innerHTML = '';
                currentTags_{widget_id}.forEach(function(tag) {{
                    var pill = document.createElement('span');
                    pill.className = 'tag-pill';
                    pill.setAttribute('data-tag', tag);
                    applyTagStyle_{widget_id}(pill, tag);

                    var tagText = document.createTextNode(tag);
                    pill.appendChild(tagText);

                    var removeBtn = document.createElement('button');
                    removeBtn.type = 'button';
                    removeBtn.className = 'tag-remove-btn';
                    removeBtn.setAttribute('data-tag-name', tag);
                    removeBtn.innerHTML = '&times;';
                    pill.appendChild(removeBtn);

                    container.appendChild(pill);
                }});
            }};

            // Add event delegation for remove buttons
            document.getElementById('{widget_id}_pills').addEventListener('click', function(event) {{
                if (event.target.classList.contains('tag-remove-btn')) {{
                    var tagName = event.target.getAttribute('data-tag-name');
                    if (tagName) {{
                        removeTag_{widget_id}(tagName);
                    }}
                }}
            }});

            document.getElementById('{widget_id}').addEventListener('change', function() {{
                syncTagEditorFromHidden_{widget_id}();
            }});

            document.getElementById('{widget_id}').addEventListener('archivebox:sync-tags', function() {{
                syncTagEditorFromHidden_{widget_id}();
            }});

            window.handleTagKeydown_{widget_id} = function(event) {{
                var input = event.target;
                var value = input.value.trim();
                var isSpace = event.key === ' ' || event.code === 'Space' || event.key === 'Spacebar';
                var isEnter = event.key === 'Enter' || event.keyCode === 13;
                var isComma = event.key === ',';

                if (isEnter || isSpace || isComma) {{
                    event.preventDefault();
                    event.stopPropagation();
                    if (value) {{
                        // Treat commas and whitespace as tag boundaries.
                        value.split(/[\s,]+/).forEach(function(tag) {{
                            addTag_{widget_id}(tag.trim());
                        }});
                    }}
                    return false;
                }} else if (event.key === 'Backspace' && !value && currentTags_{widget_id}.length > 0) {{
                    // Remove last tag on backspace when input is empty
                    var lastTag = currentTags_{widget_id}.pop();
                    rebuildPills_{widget_id}();
                    updateHiddenInput_{widget_id}();
                }}
            }};

            window.fetchTagAutocomplete_{widget_id} = function(query) {{
                if (autocompleteTimeout_{widget_id}) {{
                    clearTimeout(autocompleteTimeout_{widget_id});
                }}

                autocompleteTimeout_{widget_id} = setTimeout(function() {{
                    if (!query || query.length < 1) {{
                        document.getElementById('{widget_id}_datalist').innerHTML = '';
                        return;
                    }}

                    fetch(buildApiUrl('/api/v1/core/tags/autocomplete/?q=' + encodeURIComponent(query)))
                        .then(function(response) {{ return response.json(); }})
                        .then(function(data) {{
                            var datalist = document.getElementById('{widget_id}_datalist');
                            datalist.innerHTML = '';
                            (data.tags || []).forEach(function(tag) {{
                                var option = document.createElement('option');
                                option.value = tag.name;
                                datalist.appendChild(option);
                            }});
                        }})
                        .catch(function(err) {{
                            console.log('Autocomplete error:', err);
                        }});
                }}, 150);
            }};

            function escapeHtml(text) {{
                var div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }}

            function getCSRFToken() {{
                var cookies = document.cookie.split(';');
                for (var i = 0; i < cookies.length; i++) {{
                    var cookie = cookies[i].trim();
                    if (cookie.startsWith('csrftoken=')) {{
                        return cookie.substring('csrftoken='.length);
                    }}
                }}
                // Fallback to hidden input
                var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
                return input ? input.value : '';
            }}

            syncTagEditorFromHidden_{widget_id}();
        }})();
        </script>
        '''

        return mark_safe(html)


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
        allowlist = escape(value.get("allowlist", "") or "")
        denylist = escape(value.get("denylist", "") or "")

        return mark_safe(f'''
        <div id="{widget_id}_container" class="url-filters-widget">
            <input type="hidden" name="{name}" value="">
            <div class="url-filters-grid">
                <div class="url-filters-column">
                    <div class="url-filter-label-row">
                        <label for="{widget_id}_allowlist" class="url-filter-label"><span class="url-filter-label-main">🟢 URL_ALLOWLIST</span></label>
                        <span class="url-filter-label-note">Regex patterns or domains to exclude, one pattern per line.</span>
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
                <input type="checkbox" id="{widget_id}_same_domain_only" name="{name}_same_domain_only" value="1">
                <span>Same domain only</span>
            </label>
            <div class="help-text">These values can be one regex pattern or domain per line. URL_DENYLIST takes precedence over URL_ALLOWLIST.</div>
            <script>
            (function() {{
                var allowlistField = document.getElementById('{widget_id}_allowlist');
                var denylistField = document.getElementById('{widget_id}_denylist');
                var sameDomainOnly = document.getElementById('{widget_id}_same_domain_only');
                var sourceField = document.querySelector({json.dumps(self.source_selector)});
                var lastAutoGeneratedAllowlist = '';
                if (!allowlistField || !sameDomainOnly || !sourceField) {{
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
                    if (!sameDomainOnly.checked) {{
                        if (allowlistField.value.trim() === lastAutoGeneratedAllowlist) {{
                            allowlistField.value = '';
                            syncConfigEditor();
                        }}
                        lastAutoGeneratedAllowlist = '';
                        return;
                    }}

                    var seen = Object.create(null);
                    var domains = [];
                    sourceField.value.split(/\\n+/).forEach(function(line) {{
                        var url = extractUrl(line);
                        if (!url) {{
                            return;
                        }}
                        try {{
                            var parsed = new URL(url);
                            var domain = String(parsed.hostname || '').toLowerCase();
                            if (!domain || seen[domain]) {{
                                return;
                            }}
                            seen[domain] = true;
                            domains.push(domain);
                        }} catch (error) {{
                            return;
                        }}
                    }});
                    lastAutoGeneratedAllowlist = buildHostRegex(domains);
                    allowlistField.value = lastAutoGeneratedAllowlist;
                    syncConfigEditor();
                }}

                sameDomainOnly.addEventListener('change', syncAllowlistFromUrls);
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
            if hasattr(value, "all"):  # QuerySet
                for tag in value.all():
                    tag_data.append({"id": tag.pk, "name": tag.name})
                tag_data.sort(key=lambda x: x["name"].lower())
            elif isinstance(value, (list, tuple)):
                if value and hasattr(value[0], "name"):
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
