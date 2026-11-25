document.querySelectorAll('.key-value-editor').forEach(editor => {
    const hidden = editor.querySelector('input[type="hidden"][name]');
    const widgetId = hidden.id;
    const configMeta = JSON.parse(editor.querySelector('script[type="application/json"]').textContent);
    var rowCounter = 0;

    function stringifyValue(value) {
        return typeof value === 'string' ? value : JSON.stringify(value);
    }

    function getTypes(meta) {
        if (!meta || meta.type === undefined || meta.type === null) {
            return [];
        }
        return Array.isArray(meta.type) ? meta.type : [meta.type];
    }

    function getMetaForKey(key) {
        if (!key) {
            return null;
        }

        var explicitMeta = configMeta[key];
        if (explicitMeta) {
            return Object.assign({ key: key }, explicitMeta);
        }

        if (key.endsWith('_BINARY')) {
            return {
                key: key,
                plugin: 'custom',
                type: 'string',
                default: '',
                description: 'Path to binary executable',
            };
        }

        if (isRegexConfigKey(key)) {
            return {
                key: key,
                plugin: 'custom',
                type: 'string',
                default: '',
                description: 'Regex pattern list',
            };
        }

        return null;
    }

    function describeMeta(meta) {
        if (!meta) {
            return '';
        }

        var details = '';
        if (Array.isArray(meta.enum) && meta.enum.length) {
            details = 'Allowed: ' + meta.enum.map(stringifyValue).join(', ');
        } else {
            var types = getTypes(meta);
            if (types.length) {
                details = 'Expected: ' + types.join(' or ');
            }
        }

        if (meta.minimum !== undefined || meta.maximum !== undefined) {
            var bounds = [];
            if (meta.minimum !== undefined) bounds.push('min ' + meta.minimum);
            if (meta.maximum !== undefined) bounds.push('max ' + meta.maximum);
            details += (details ? ' ' : '') + '(' + bounds.join(', ') + ')';
        }

        return [meta.description || '', details].filter(Boolean).join(' ');
    }

    function getExampleInput(key, meta) {
        var types = getTypes(meta);
        if (key.endsWith('_BINARY')) {
            return 'Example: wget or /usr/bin/wget';
        }
        if (key.endsWith('_ARGS_EXTRA') || key.endsWith('_ARGS')) {
            return 'Example: ["--extra-arg"]';
        }
        if (types.includes('array')) {
            return 'Example: ["value"]';
        }
        if (types.includes('object')) {
            return 'Example: {"key": "value"}';
        }
        return '';
    }

    function isRegexConfigKey(key) {
        return key === 'URL_ALLOWLIST' ||
            key === 'URL_DENYLIST' ||
            key.endsWith('_PATTERN') ||
            key.includes('REGEX');
    }

    function isSimpleFilterPattern(pattern) {
        return /^[\w.*:-]+$/.test(pattern);
    }

    function validateRegexPattern(pattern) {
        if (!pattern || isSimpleFilterPattern(pattern)) {
            return '';
        }

        try {
            new RegExp(pattern);
        } catch (error) {
            return error && error.message ? error.message : 'Invalid regex';
        }
        return '';
    }

    function validateRegexConfig(key, raw, typeName) {
        if (typeName === 'object') {
            var parsed;
            try {
                parsed = JSON.parse(raw);
            } catch (error) {
                return { ok: false, value: raw, message: 'Must be valid JSON' };
            }
            if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
                return { ok: false, value: parsed, message: 'Must be a JSON object' };
            }
            for (var regexKey in parsed) {
                var objectRegexError = validateRegexPattern(regexKey);
                if (objectRegexError) {
                    return { ok: false, value: parsed, message: 'Invalid regex key "' + regexKey + '": ' + objectRegexError };
                }
            }
            return { ok: true, value: parsed, message: '' };
        }

        var patterns = raw.split(/[\n,]+/).map(function(pattern) {
            return pattern.trim();
        }).filter(Boolean);
        for (var i = 0; i < patterns.length; i++) {
            var regexError = validateRegexPattern(patterns[i]);
            if (regexError) {
                return { ok: false, value: raw, message: 'Invalid regex "' + patterns[i] + '": ' + regexError };
            }
        }
        return { ok: true, value: raw, message: '' };
    }

    function validateBinaryValue(raw) {
        if (!raw) {
            return { ok: true, value: raw, message: '' };
        }

        if (/['"`]/.test(raw)) {
            return { ok: false, value: raw, message: 'Binary paths cannot contain quotes' };
        }

        if (/[;&|<>$(){}\[\]!]/.test(raw)) {
            return { ok: false, value: raw, message: 'Binary paths can only be a binary name or absolute path' };
        }

        if (raw.startsWith('/')) {
            if (/^[A-Za-z0-9_./+\- ]+$/.test(raw)) {
                return { ok: true, value: raw, message: '' };
            }
            return { ok: false, value: raw, message: 'Absolute paths may only contain path-safe characters' };
        }

        if (/^[A-Za-z0-9_.+-]+$/.test(raw)) {
            return { ok: true, value: raw, message: '' };
        }

        return { ok: false, value: raw, message: 'Enter a binary name like wget or an absolute path like /usr/bin/wget' };
    }

    function parseValue(raw) {
        try {
            if (raw === 'true') return true;
            if (raw === 'false') return false;
            if (raw === 'null') return null;
            if (raw !== '' && !isNaN(raw)) return Number(raw);
            if ((raw.startsWith('{') && raw.endsWith('}')) ||
                (raw.startsWith('[') && raw.endsWith(']')) ||
                (raw.startsWith('"') && raw.endsWith('"'))) {
                return JSON.parse(raw);
            }
        } catch (error) {
            return raw;
        }
        return raw;
    }

    function sameValue(left, right) {
        return left === right || JSON.stringify(left) === JSON.stringify(right);
    }

    function parseTypedValue(raw, typeName, meta) {
        var numberValue;
        var parsed;

        if (typeName && meta && meta.key && isRegexConfigKey(meta.key)) {
            return validateRegexConfig(meta.key, raw, typeName);
        }

        if (typeName === 'string' && meta && meta.key && meta.key.endsWith('_BINARY')) {
            return validateBinaryValue(raw);
        }

        if (typeName === 'string') {
            if (meta.pattern) {
                try {
                    if (!(new RegExp(meta.pattern)).test(raw)) {
                        return { ok: false, value: raw, message: 'Must match pattern ' + meta.pattern };
                    }
                } catch (error) {}
            }
            return { ok: true, value: raw, message: '' };
        }

        if (typeName === 'integer') {
            if (!/^-?\d+$/.test(raw)) {
                return { ok: false, value: raw, message: 'Must be an integer' };
            }
            numberValue = Number(raw);
            if (meta.minimum !== undefined && numberValue < meta.minimum) {
                return { ok: false, value: numberValue, message: 'Must be at least ' + meta.minimum };
            }
            if (meta.maximum !== undefined && numberValue > meta.maximum) {
                return { ok: false, value: numberValue, message: 'Must be at most ' + meta.maximum };
            }
            return { ok: true, value: numberValue, message: '' };
        }

        if (typeName === 'number') {
            if (raw === '' || isNaN(raw)) {
                return { ok: false, value: raw, message: 'Must be a number' };
            }
            numberValue = Number(raw);
            if (meta.minimum !== undefined && numberValue < meta.minimum) {
                return { ok: false, value: numberValue, message: 'Must be at least ' + meta.minimum };
            }
            if (meta.maximum !== undefined && numberValue > meta.maximum) {
                return { ok: false, value: numberValue, message: 'Must be at most ' + meta.maximum };
            }
            return { ok: true, value: numberValue, message: '' };
        }

        if (typeName === 'boolean') {
            var lowered = raw.toLowerCase();
            if (lowered === 'true' || raw === '1') return { ok: true, value: true, message: '' };
            if (lowered === 'false' || raw === '0') return { ok: true, value: false, message: '' };
            return { ok: false, value: raw, message: 'Must be true or false' };
        }

        if (typeName === 'null') {
            return raw === 'null'
                ? { ok: true, value: null, message: '' }
                : { ok: false, value: raw, message: 'Must be null' };
        }

        if (typeName === 'array' || typeName === 'object') {
            try {
                parsed = JSON.parse(raw);
            } catch (error) {
                return { ok: false, value: raw, message: 'Must be valid JSON' };
            }

            if (typeName === 'array' && Array.isArray(parsed)) {
                return { ok: true, value: parsed, message: '' };
            }
            if (typeName === 'object' && parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                return { ok: true, value: parsed, message: '' };
            }

            return {
                ok: false,
                value: parsed,
                message: typeName === 'array' ? 'Must be a JSON array' : 'Must be a JSON object',
            };
        }

        return { ok: true, value: parseValue(raw), message: '' };
    }

    function validateValueAgainstMeta(raw, meta) {
        if (!meta || raw === '') {
            return { state: 'neutral', value: raw, message: '' };
        }

        var enumValues = Array.isArray(meta.enum) ? meta.enum : [];
        var types = getTypes(meta);
        if (!types.length) {
            types = ['string'];
        }

        var error = 'Invalid value';
        for (var i = 0; i < types.length; i++) {
            var candidate = parseTypedValue(raw, types[i], meta);
            if (!candidate.ok) {
                error = candidate.message || error;
                continue;
            }
            if (enumValues.length && !enumValues.some(function(enumValue) {
                return sameValue(enumValue, candidate.value) || stringifyValue(enumValue) === raw;
            })) {
                error = 'Must be one of: ' + enumValues.map(stringifyValue).join(', ');
                continue;
            }
            return { state: 'valid', value: candidate.value, message: '' };
        }

        return { state: 'invalid', value: raw, message: error };
    }

    function ensureRowId(row) {
        if (!row.dataset.rowId) {
            row.dataset.rowId = String(rowCounter++);
        }
        return row.dataset.rowId;
    }

    function setRowHelp(row) {
        var keyInput = row.querySelector('.kv-key');
        var help = row.querySelector('.kv-help');
        if (!keyInput || !help) {
            return;
        }

        var key = keyInput.value.trim();
        if (!key) {
            help.textContent = '';
            return;
        }

        var meta = getMetaForKey(key);
        if (meta) {
            var extra = isRegexConfigKey(key)
                ? ((meta.type === 'object' || (Array.isArray(meta.type) && meta.type.includes('object')))
                    ? ' Expected: JSON object with regex keys.'
                    : ' Expected: valid regex.')
                : '';
            var example = getExampleInput(key, meta);
            help.textContent = [describeMeta(meta) + extra, example].filter(Boolean).join(' ');
        } else {
            help.textContent = 'Custom key';
        }
    }

    function configureValueInput(row) {
        var keyInput = row.querySelector('.kv-key');
        var valueInput = row.querySelector('.kv-value');
        var datalist = row.querySelector('.kv-value-options');
        if (!keyInput || !valueInput || !datalist) {
            return;
        }

        var rowId = ensureRowId(row);
        datalist.id = widgetId + '_value_options_' + rowId;

        var meta = getMetaForKey(keyInput.value.trim());
        var enumValues = Array.isArray(meta && meta.enum) ? meta.enum : [];
        var types = getTypes(meta);
        if (!enumValues.length && types.includes('boolean')) {
            enumValues = ['True', 'False'];
        }
        if (enumValues.length) {
            datalist.innerHTML = enumValues.map(function(enumValue) {
                return '<option value="' + stringifyValue(enumValue).replace(/"/g, '&quot;') + '"></option>';
            }).join('');
            valueInput.setAttribute('list', datalist.id);
        } else {
            datalist.innerHTML = '';
            valueInput.removeAttribute('list');
        }
    }

    function setValueValidationState(input, state, message) {
        if (!input) {
            return;
        }

        if (state === 'valid') {
            input.style.borderColor = '#2da44e';
            input.style.boxShadow = '0 0 0 1px rgba(45, 164, 78, 0.18)';
            input.style.backgroundColor = '#f6ffed';
        } else if (state === 'invalid') {
            input.style.borderColor = '#cf222e';
            input.style.boxShadow = '0 0 0 1px rgba(207, 34, 46, 0.18)';
            input.style.backgroundColor = '#fff8f8';
        } else {
            input.style.borderColor = '#ccc';
            input.style.boxShadow = 'none';
            input.style.backgroundColor = '';
        }
        input.title = message || '';
    }

    function applyValueValidation(row) {
        var keyInput = row.querySelector('.kv-key');
        var valueInput = row.querySelector('.kv-value');
        if (!keyInput || !valueInput) {
            return;
        }

        var key = keyInput.value.trim();
        if (!key) {
            setValueValidationState(valueInput, 'neutral', '');
            return;
        }

        var meta = getMetaForKey(key);
        if (!meta) {
            setValueValidationState(valueInput, 'neutral', '');
            return;
        }

        var validation = validateValueAgainstMeta(valueInput.value.trim(), meta);
        setValueValidationState(valueInput, validation.state, validation.message);
    }

    function coerceValueForStorage(key, raw) {
        var meta = getMetaForKey(key);
        if (!meta) {
            return parseValue(raw);
        }

        var validation = validateValueAgainstMeta(raw, meta);
        return validation.state === 'valid' ? validation.value : raw;
    }

    function initializeRows() {
        var container = editor.querySelector('.key-value-rows');
        container.querySelectorAll('.key-value-row').forEach(function(row) {
            ensureRowId(row);
            configureValueInput(row);
            setRowHelp(row);
            applyValueValidation(row);
        });
    }

    function updateHiddenField() {
        var container = editor.querySelector('.key-value-rows');
        var rows = container.querySelectorAll('.key-value-row');
        var result = [];
        rows.forEach(function(row) {
            var keyInput = row.querySelector('.kv-key');
            var valInput = row.querySelector('.kv-value');
            if (keyInput && valInput && keyInput.value.trim()) {
                var key = keyInput.value.trim();
                var val = valInput.value.trim();
                // Keep untouched values byte-exact, including numeric-looking strings
                // and JSON numbers outside JavaScript's safe integer range.
                var original = row.getAttribute('data-original-json');
                var unchanged = original !== null && keyInput.value === keyInput.defaultValue &&
                    valInput.value === valInput.defaultValue;
                var serialized = unchanged ? original : JSON.stringify(coerceValueForStorage(key, val));
                result.push(JSON.stringify(key) + ':' + serialized);
            }
        });
        hidden.value = '{' + result.join(',') + '}';
    }

    function addKeyValueRow() {
        var container = editor.querySelector('.key-value-rows');
        var newRow = document.createElement('div');
        newRow.className = 'key-value-row';
        newRow.style.cssText = 'margin-bottom: 6px;';
        newRow.innerHTML = '<div class="kv-inputs" style="display: flex; gap: 8px; align-items: center;">' +
            '<input type="text" class="kv-key" placeholder="KEY" list="' + widgetId + '_keys" ' +
            'style="flex: 1; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 12px;">' +
            '<input type="text" class="kv-value" placeholder="value" ' +
            'style="flex: 2; padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-family: monospace; font-size: 12px;">' +
            '<datalist class="kv-value-options"></datalist>' +
            '<button type="button" data-remove-config-row ' +
            'style="padding: 4px 10px; cursor: pointer; background: #ba2121; color: white; border: none; border-radius: 4px; font-weight: bold;">−</button>' +
            '</div>' +
            '<div class="kv-help" style="margin-top: 4px; font-size: 11px; color: #666; font-style: italic;"></div>';
        container.appendChild(newRow);
        ensureRowId(newRow);
        configureValueInput(newRow);
        setRowHelp(newRow);
        applyValueValidation(newRow);
        updateHiddenField();
        newRow.querySelector('.kv-key').focus();
    }

    function removeKeyValueRow(btn) {
        var row = btn.closest('.key-value-row');
        row.remove();
        updateHiddenField();
    }

    // Other form widgets use these hooks to synchronize their structured controls.
    window['addKeyValueRow_' + widgetId] = addKeyValueRow;
    window['removeKeyValueRow_' + widgetId] = removeKeyValueRow;
    window['updateHiddenField_' + widgetId] = updateHiddenField;

    function configRowForKey(key) {
        var container = editor.querySelector('.key-value-rows');
        if (!container) {
            return null;
        }
        var match = null;
        container.querySelectorAll('.key-value-row').forEach(function(row) {
            if (match) { return; }
            var keyInput = row.querySelector('.kv-key');
            if (keyInput && keyInput.value.trim() === key) {
                match = row;
            }
        });
        if (!match) {
            addKeyValueRow();
            var rows = container.querySelectorAll('.key-value-row');
            match = rows[rows.length - 1];
            var keyInput = match.querySelector('.kv-key');
            if (keyInput) {
                keyInput.value = key;
                keyInput.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }
        return match;
    }

    function prefillConfigFromQuery() {
        var params = new URLSearchParams(window.location.search);
        var consumedConfigKeys = [];
        params.forEach(function(value, key) {
            if (!/^[A-Z][A-Z0-9_]*$/.test(key) || !configMeta[key]) {
                return;
            }
            consumedConfigKeys.push(key);
            var match = configRowForKey(key);
            var valueInput = match && match.querySelector('.kv-value');
            if (valueInput) {
                valueInput.value = value;
                valueInput.dispatchEvent(new Event('input', { bubbles: true }));
            }
        });
        updateHiddenField();
        if (consumedConfigKeys.length) {
            var cleanUrl = new URL(window.location.href);
            consumedConfigKeys.forEach(function(key) { cleanUrl.searchParams.delete(key); });
            window.history.replaceState(null, '', cleanUrl.pathname + cleanUrl.search + cleanUrl.hash);
        }
    }

    function focusConfigKeyFromHash() {
        // Deep-link affordance: ``…/change/#SOME_KEY`` jumps directly
        // to (or creates) the matching row in this editor. Used by
        // the setup wizard and live-config detail pages.
        var hash = (window.location.hash || '').replace(/^#/, '').trim();
        if (!hash || !/^[A-Z][A-Z0-9_]*$/.test(hash)) {
            return;
        }
        var match = configRowForKey(hash);
        if (!match) {
            return;
        }
        match.scrollIntoView({ behavior: 'smooth', block: 'center' });
        var prevOutline = match.style.outline;
        match.style.outline = '2px solid #f59e0b';
        match.style.outlineOffset = '2px';
        match.style.transition = 'outline 1.2s ease-out';
        setTimeout(function() {
            match.style.outline = prevOutline || 'none';
        }, 1400);
        var valueInput = match.querySelector('.kv-value');
        if (valueInput) {
            valueInput.focus();
            try { valueInput.setSelectionRange(valueInput.value.length, valueInput.value.length); } catch (e) {}
        }
    }

    editor.addEventListener('click', event => {
        const remove = event.target.closest('[data-remove-config-row]');
        if (remove) removeKeyValueRow(remove);
        if (event.target.closest('[data-add-config-row]')) addKeyValueRow();
    });

    // Native autocomplete needs its options only when someone edits a key.
    // The same datalist is already in the document when scripting is disabled.
    editor.addEventListener('focusin', function loadOptions(event) {
        if (!event.target.matches('.kv-key')) return;
        const source = editor.querySelector('noscript');
        source.insertAdjacentHTML('afterend', source.textContent);
        source.remove();
        editor.removeEventListener('focusin', loadOptions);
    });

    window.addEventListener('hashchange', focusConfigKeyFromHash);

    // Update on any input change
    var rowsEl = editor.querySelector('.key-value-rows');

    rowsEl.addEventListener('input', function(event) {
        var row = event.target.closest('.key-value-row');
        if (!row) {
            return;
        }

        if (event.target.classList.contains('kv-key')) {
            configureValueInput(row);
            setRowHelp(row);
        }

        if (event.target.classList.contains('kv-key') || event.target.classList.contains('kv-value')) {
            applyValueValidation(row);
            updateHiddenField();
        }
    });

    // Install the editor hooks before other deferred widgets run. Where both
    // the setup wizard and editor consume query parameters, let the wizard
    // select its plugin before the editor removes the consumed parameters.
    document.addEventListener('DOMContentLoaded', () => {
        initializeRows();
        prefillConfigFromQuery();
        updateHiddenField();
        focusConfigKeyFromHash();
    }, {once: true});
});
