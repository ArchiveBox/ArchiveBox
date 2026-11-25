// Snapshot the submitted values after deferred Add initialization, before
// Machine's DOMContentLoaded handler applies edits from the setup wizard.
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.plugin-config-form').forEach(settings => {
        const form = settings.closest('form');
        if (!form) return;
        // Shared settings reveal invalid controls in hidden tabs before saving.
        // Django admin's default novalidate otherwise bypasses that handler.
        form.noValidate = false;
        const value = input => input.multiple ? JSON.stringify([...input.selectedOptions].map(option => option.value)) : input.type === 'checkbox' ? input.checked : input.value;
        const inputs = [...settings.querySelectorAll('.plugin-config-input[name][data-config-key]')];
        const original = new Map(inputs.map(input => [input, value(input)]));
        const pending = [...form.querySelectorAll('[name="settings_changed"]')].map(input => input.value);
        const marker = document.createElement('input');
        marker.type = 'hidden'; marker.name = 'settings_editor'; marker.value = '1'; form.append(marker);
        const mark = event => event.target.closest('.plugin-config-field')?.classList.add('settings-edited');
        settings.addEventListener('input', mark);
        settings.addEventListener('change', mark);
        form.addEventListener('submit', () => {
            form.querySelectorAll('[name="settings_changed"]').forEach(input => input.remove());
            const changed = new Set([...pending, ...inputs.filter(input => value(input) !== original.get(input)).map(input => input.dataset.configKey)]);
            changed.forEach(key => {
                const input = document.createElement('input');
                input.type = 'hidden'; input.name = 'settings_changed'; input.value = key; form.append(input);
            });
        });
        // A toolbar can be clicked while the browser is still parsing the form.
        // Enable submission only after widgets and change tracking are ready.
        document.querySelectorAll('[data-settings-submit]').forEach(control => {
            if (control.form === form) control.disabled = false;
        });
    });
}, {capture: true});

(function() {
    if (window.archiveboxPluginConfigSyncLoaded) return;
    window.archiveboxPluginConfigSyncLoaded = true;
    let syncing = false;
    document.querySelectorAll('.plugin-config-form').forEach(settings => {
        const tabs = Array.from(settings.querySelectorAll('[role="tab"]'));
        const search = settings.querySelector('input[type="search"]');
        const empty = settings.querySelector('.plugin-settings-empty');
        const panelFor = tab => document.getElementById(tab.getAttribute('aria-controls'));
        let selected = null;

        function select(tab, focus = false) {
            const changed = selected && selected !== tab;
            selected = tab;
            tabs.forEach(item => {
                const active = item === tab;
                item.setAttribute('aria-selected', String(active));
                item.tabIndex = active ? 0 : -1;
                const sidebar = item.closest('.plugin-settings-nav-row').querySelector('.plugin-sidebar-toggle');
                if (sidebar) sidebar.tabIndex = active ? 0 : -1;
                panelFor(item).hidden = !active;
            });
            if (changed) settings.querySelector('.plugin-settings-content').scrollTop = 0;
            if (changed && settings.getBoundingClientRect().top < 0) settings.scrollIntoView({block: 'start'});
            if (tab && focus) tab.focus();
        }
        function filter() {
            const query = search.value.trim().toLowerCase();
            tabs.forEach(tab => {
                const panel = panelFor(tab);
                const pluginMatches = !query || `${tab.dataset.plugin} ${tab.textContent} ${panel.dataset.pluginEnabledKey || ''}`.toLowerCase().includes(query);
                let matches = pluginMatches;
                panel.querySelectorAll('.plugin-config-field').forEach(field => {
                    field.hidden = !pluginMatches && !`${field.dataset.search} ${field.querySelector('label').textContent}`.toLowerCase().includes(query);
                    matches ||= !field.hidden;
                });
                panel.querySelectorAll('.config-field-section').forEach(section => {
                    section.hidden = !section.querySelector('.plugin-config-field:not([hidden])');
                });
                if (query) panel.querySelectorAll('.plugin-advanced').forEach(details => { details.open = Boolean(details.querySelector('.plugin-config-field:not([hidden])')); });
                tab.hidden = !matches;
                tab.closest('.plugin-settings-nav-row').hidden = !matches;
            });
            settings.querySelectorAll('.plugin-settings-nav-group').forEach(group => {
                group.hidden = !Array.from(group.querySelectorAll('[role="tab"]')).some(tab => !tab.hidden);
            });
            const visible = tabs.filter(tab => !tab.hidden);
            empty.hidden = visible.length > 0;
            const exact = query && visible.find(tab => tab.dataset.plugin.toLowerCase() === query || tab.querySelector('.plugin-choice-name')?.textContent.trim().toLowerCase() === query);
            select(exact || (selected && !selected.hidden ? selected : visible[0] || null));
        }
        tabs.forEach(tab => {
            tab.addEventListener('click', () => select(tab));
            tab.addEventListener('keydown', event => {
                const visible = tabs.filter(item => !item.hidden);
                const index = visible.indexOf(tab);
                let next;
                if (event.key === 'ArrowDown') next = visible[(index + 1) % visible.length];
                if (event.key === 'ArrowUp') next = visible[(index - 1 + visible.length) % visible.length];
                if (event.key === 'Home') next = visible[0];
                if (event.key === 'End') next = visible[visible.length - 1];
                if (next) { event.preventDefault(); select(next, true); }
            });
        });
        search.addEventListener('input', filter);
        search.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === 'ArrowDown') {
                event.preventDefault();
                if (selected) selected.focus();
            }
            if (event.key === 'Escape') { search.value = ''; filter(); }
        });
        // Native form validation must reveal the field even when another tab is selected.
        settings.addEventListener('invalid', event => {
            const panel = event.target.closest('.plugin-card');
            if (!panel || event.target !== settings.querySelector(':invalid')) return;
            search.value = '';
            filter();
            select(tabs.find(tab => panelFor(tab) === panel));
            const advanced = event.target.closest('.plugin-advanced');
            if (advanced) advanced.open = true;
        }, true);
        function updateStatus(tab, toggle) {
            const sidebar = tab?.closest('.plugin-settings-nav-row').querySelector('.plugin-sidebar-toggle');
            const checked = Boolean(toggle?.checked);
            if (sidebar && sidebar.checked !== checked) sidebar.checked = checked;
        }
        function updateAllStatuses() {
            tabs.forEach(tab => {
                const panel = panelFor(tab);
                updateStatus(tab, getCardSectionToggle(panel) || getCardEnabledInput(panel));
            });
        }
        settings.addEventListener('change', event => {
            const input = event.target;
            if (input.matches('.plugin-sidebar-toggle')) {
                const tab = input.closest('.plugin-settings-nav-row').querySelector('[role="tab"]');
                const panel = panelFor(tab);
                const toggle = getCardSectionToggle(panel) || getCardEnabledInput(panel);
                setChecked(toggle, input.checked);
                updateStatus(tab, toggle);
                return;
            }
            const panel = input.closest('.plugin-card');
            if (!panel || (input.dataset.configKey !== panel.dataset.pluginEnabledKey && !input.matches('.plugin-section-toggle'))) return;
            const toggle = getCardSectionToggle(panel) || getCardEnabledInput(panel);
            if (input === toggle) updateStatus(document.getElementById(panel.getAttribute('aria-labelledby')), toggle);
        });
        let statusUpdateQueued = false;
        settings.addEventListener('plugin-config-updated', () => {
            // Applying a persona can update both the fields and the switches.
            // Reflect their final state once instead of revisiting every row twice.
            if (statusUpdateQueued) return;
            statusUpdateQueued = true;
            queueMicrotask(() => {
                statusUpdateQueued = false;
                updateAllStatuses();
            });
        });
        // Every field is initially visible in the server markup. An empty
        // search just needs the first tab, without rewriting each field.
        if (search.value || !tabs.length) filter();
        else select(tabs[0]);
        function selectSettingsPanel(panelId, focus = false) {
            const linkedTab = tabs.find(tab => tab.getAttribute('aria-controls') === panelId);
            if (!linkedTab) return;
            if (focus && search.value) {
                search.value = '';
                filter();
            }
            select(linkedTab);
            if (focus) panelFor(linkedTab).focus();
        }
        selectSettingsPanel(window.location.hash.slice(1));
        settings.querySelectorAll('[data-provider-keys-link]').forEach(link => {
            link.addEventListener('click', event => {
                if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
                selectSettingsPanel(link.hash.slice(1), true);
            });
        });
        updateAllStatuses();
        // Do not lose sidebar interactions while the settings form is still parsing.
        tabs.forEach(tab => { tab.disabled = false; });
        search.disabled = false;
        settings.querySelectorAll('.plugin-sidebar-toggle').forEach(toggle => { toggle.disabled = false; });
    });

    function updateWidget(field) {
        const input = field.querySelector('.plugin-config-input');
        if (!input) return;
        const counter = field.querySelector('[data-editor-count]');
        if (counter) counter.textContent = `${input.value.length} characters`;
        const slider = field.querySelector('.config-range-slider');
        if (slider) {
            if (slider.matches('.config-limit-slider')) {
                const max = Number(input.max) || Math.max(Number(slider.dataset.defaultMax), Number(input.value) || 0);
                slider.max = max;
                const label = field.querySelector('[data-limit-max]');
                const units = label.dataset.unit === 'bytes-decimal' ? [[1, 'B'], [1e3, 'kB'], [1e6, 'MB'], [1e9, 'GB'], [1e12, 'TB']] : [[1, 'B'], [1024, 'KiB'], [1048576, 'MiB'], [1073741824, 'GiB'], [1099511627776, 'TiB']];
                const [factor, unit] = ['B', 'bytes-decimal'].includes(label.dataset.unit) ? units.filter(([factor]) => factor <= max).at(-1) || units[0] : [1, label.dataset.unit];
                label.textContent = `${(max / factor).toLocaleString()} ${unit}`;
            }
            if (slider.matches('.config-timeout-slider')) {
                const value = Number(input.value);
                if (!input.hasAttribute('max') && Number.isFinite(value)) slider.max = Math.max(Number(slider.dataset.defaultMax), value);
                const unit = slider.dataset.unit;
                const durationLabel = value => {
                    const seconds = unit === 'ms' ? value / 1000 : value;
                    return seconds >= 3600 && seconds % 3600 === 0 ? `${seconds / 3600} hr` : seconds >= 60 && seconds % 60 === 0 ? `${seconds / 60} min` : `${value} ${unit}`;
                };
                field.querySelector('[data-timeout-min]').textContent = input.dataset.configKey === 'CRAWL_TIMEOUT' && Number(slider.min) === 0 ? 'No limit' : durationLabel(Number(slider.min));
                field.querySelector('[data-timeout-max]').textContent = durationLabel(Number(slider.max));
            }
            slider.value = input.value;
        }
        field.querySelectorAll('[data-config-preset]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.configPreset === input.value)));
    }

    function updateWidgets() {
        // Most settings are plain inputs with nothing to update.
        const widgets = document.querySelectorAll('[data-editor-count], .config-range-slider, [data-config-preset]');
        new Set([...widgets].map(widget => widget.closest('.plugin-config-field')).filter(Boolean)).forEach(updateWidget);
    }
    document.addEventListener('click', event => {
        const snippet = event.target.closest('[data-config-insert], [data-config-wrap]');
        if (snippet) {
            const input = snippet.closest('.plugin-config-field').querySelector('textarea');
            let code = snippet.dataset.configWrap || snippet.dataset.configInsert;
            if (snippet.dataset.configSource) {
                const source = snippet.closest('.plugin-card').querySelector(`.plugin-config-input[data-config-key="${CSS.escape(snippet.dataset.configSource)}"]`);
                code = code.replace('__VALUE__', () => JSON.stringify(source?.value || snippet.dataset.configSourceDefault || ''));
            }
            if (snippet.dataset.configWrap) {
                code = code.replace('__SCRIPT__', () => input.value || '  // Add steps for this domain here.');
                input.setRangeText(code, 0, input.value.length, 'end');
            } else if (snippet.dataset.configPosition === 'start') {
                input.setRangeText(code + '\n', 0, 0, 'end');
            } else {
                const prefix = input.selectionStart > 0 && input.value[input.selectionStart - 1] !== '\n' ? '\n' : '';
                input.setRangeText(prefix + code, input.selectionStart, input.selectionEnd, 'end');
            }
            input.focus();
            input.dispatchEvent(new Event('input', {bubbles: true}));
            input.dispatchEvent(new Event('change', {bubbles: true}));
            return;
        }
        const button = event.target.closest('[data-config-preset]');
        if (!button) return;
        const input = button.closest('.plugin-config-field').querySelector('.plugin-config-input');
        input.value = button.dataset.configPreset;
        input.dispatchEvent(new Event('input', {bubbles:true}));
        input.dispatchEvent(new Event('change', {bubbles:true}));
    });
    document.addEventListener('input', event => {
        if (event.target.matches('.config-range-slider')) {
            const input = event.target.closest('.plugin-config-field').querySelector('.plugin-config-input');
            input.value = event.target.value;
            input.dispatchEvent(new Event('input', {bubbles:true}));
        }
    });
    updateWidgets();

    function valueToFieldString(value) {
        if (value === undefined || value === null) return '';
        if (typeof value === 'object') return JSON.stringify(value, null, 2);
        return String(value);
    }

    function setPluginInputValue(input, value) {
        if (input.multiple) {
            const selected = new Set((Array.isArray(value) ? value : []).map(String));
            let changed = false;
            for (const option of input.options) {
                const enabled = selected.has(option.value);
                if (option.selected === enabled) continue;
                option.selected = enabled;
                changed = true;
            }
            return changed;
        } else if (input.type === 'checkbox') {
            const checked = value === true || value === 'true' || value === '1' || value === 'on';
            if (input.checked === checked) return false;
            input.checked = checked;
            return true;
        }
        const text = valueToFieldString(value);
        if (input.value === text) return false;
        input.value = text;
        return true;
    }

    function getPluginInputValue(input) {
        return input.multiple ? [...input.selectedOptions].map(option => option.value) : input.type === 'checkbox' ? input.checked : input.value;
    }

    function syncMatchingPluginInputs(source) {
        if (syncing || !source || !source.dataset.configKey) return;
        syncing = true;
        const value = getPluginInputValue(source);
        document.querySelectorAll(`.plugin-config-input[data-config-key="${CSS.escape(source.dataset.configKey)}"]`).forEach((input) => {
            if (input !== source) {
                if (!setPluginInputValue(input, value)) return;
                window.archiveboxRefreshQuantities?.(input);
            }
            const field = input.closest('.plugin-config-field');
            if (field) updateWidget(field);
        });
        syncing = false;
    }

    function dispatchPluginInputChange(input) {
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function setChecked(input, checked, shouldDispatch = true) {
        if (!input || input.checked === checked) return;
        input.checked = checked;
        if (shouldDispatch) dispatchPluginInputChange(input);
    }

    function getCardEnabledInput(card) {
        if (!card || !card.dataset.pluginEnabledKey) return null;
        return card.querySelector(`.plugin-config-input[data-config-key="${CSS.escape(card.dataset.pluginEnabledKey)}"]`);
    }

    function getCardSectionToggle(card) {
        return card ? card.querySelector('.plugin-section-toggle') : null;
    }

    function syncEnabledInputFromSectionToggle(sectionToggle) {
        const card = sectionToggle ? sectionToggle.closest('.plugin-card') : null;
        const enabledInput = getCardEnabledInput(card);
        if (!enabledInput) return;
        setChecked(enabledInput, sectionToggle.checked);
    }

    function syncSectionToggleFromEnabledInput(enabledInput) {
        const card = enabledInput ? enabledInput.closest('.plugin-card') : null;
        if (!card || enabledInput.dataset.configKey !== card.dataset.pluginEnabledKey) return;
        setChecked(getCardSectionToggle(card), enabledInput.checked);
    }

    function setPluginCurrentValue(container, value, currentUrl) {
        let code = container.querySelector('code');
        if (!code) {
            code = document.createElement('code');
            container.textContent = '';
            container.appendChild(code);
        }
        const text = valueToFieldString(value);
        if (code.textContent !== text) code.textContent = text;
        const existingLink = container.querySelector('a');
        if (currentUrl && existingLink) {
            if (existingLink.getAttribute('href') !== currentUrl) existingLink.href = currentUrl;
        } else if (currentUrl && !existingLink) {
            const link = document.createElement('a');
            link.href = currentUrl;
            link.target = '_blank';
            link.rel = 'noopener';
            container.textContent = '';
            link.appendChild(code);
            container.appendChild(link);
        } else if (!currentUrl && existingLink) {
            container.textContent = '';
            container.appendChild(code);
        }
    }

    window.archiveboxSetPluginConfigValues = function(values, binaryUrls) {
        if (!values || typeof values !== 'object') return;
        syncing = true;
        document.querySelectorAll('.plugin-config-input[data-config-key]').forEach((input) => {
            if (Object.prototype.hasOwnProperty.call(values, input.dataset.configKey)) {
                setPluginInputValue(input, values[input.dataset.configKey]);
            }
        });
        // Input and current-value elements can share keys in multiple panels.
        // Walk each collection once when applying a persona to the whole form.
        document.querySelectorAll('.plugin-config-current[data-config-key]').forEach(container => {
            const key = container.dataset.configKey;
            if (Object.prototype.hasOwnProperty.call(values, key)) {
                setPluginCurrentValue(container, values[key], binaryUrls?.[key]);
            }
        });
        syncing = false;
        updateWidgets();
        if (window.archiveboxRefreshQuantities) window.archiveboxRefreshQuantities();
        document.querySelectorAll('.plugin-config-form').forEach(settings => settings.dispatchEvent(new Event('plugin-config-updated')));
    };

    document.addEventListener('input', function(event) {
        if (!event.target || !event.target.matches('.plugin-config-input')) return;
        syncMatchingPluginInputs(event.target);
        syncSectionToggleFromEnabledInput(event.target);
    });
    document.addEventListener('change', function(event) {
        if (!event.target) return;
        if (event.target.matches('.plugin-section-toggle')) {
            syncEnabledInputFromSectionToggle(event.target);
            return;
        }
        if (event.target.matches('.plugin-config-input')) {
            syncMatchingPluginInputs(event.target);
            syncSectionToggleFromEnabledInput(event.target);
        }
    });

})();

(() => {
    if (window.archiveboxPluginPreviewsInstalled) return;
    window.archiveboxPluginPreviewsInstalled = true;
    const initialize = () => {
        const observer = new IntersectionObserver(entries => entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            observer.unobserve(entry.target);
            const image = entry.target.querySelector('[data-plugin-preview-src]');
            if (!image) return;
            const link = image.closest('.config-plugin-preview');
            image.addEventListener('load', () => { link.hidden = false; }, {once: true});
            image.addEventListener('error', () => { link.remove(); }, {once: true});
            image.src = image.dataset.pluginPreviewSrc;
        }));
        document.querySelectorAll('[data-plugin-preview-src]').forEach(image => {
            const card = image.closest('.plugin-card');
            if (card) observer.observe(card);
        });
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, {once: true}); else initialize();
})();
