(() => {
    if (window.archiveboxRefreshQuantities) return;
    const widgets = new Map();
    const zeroWidgets = new Map();
    const zeroLabels = {CRAWL_MAX_URLS: 'No limit', CRAWL_MAX_SIZE: 'No limit', SNAPSHOT_MAX_SIZE: 'No limit', CRAWL_TIMEOUT: 'No limit', DELETE_AFTER: 'Keep forever'};
    const configKey = input => input.dataset.configKey || (input.name === 'max_urls' ? 'CRAWL_MAX_URLS' : input.name.toUpperCase());
    const durationUnits = [['ms', 'ms', .001], ['s', 'sec', 1], ['min', 'min', 60], ['h', 'hours', 3600], ['d', 'days', 86400]];
    const sizeUnits = [['B', 'bytes', 1], ['KB', 'KB', 1000], ['KiB', 'KiB', 1024], ['MB', 'MB', 1000000], ['MiB', 'MiB', 1048576], ['GB', 'GB', 1000000000], ['GiB', 'GiB', 1073741824], ['TB', 'TB', 1000000000000], ['TiB', 'TiB', 1099511627776]];
    const retentionUnits = [['h', 'hours', 3600], ['d', 'days', 86400], ['w', 'weeks', 604800], ['mo', 'months', 2592000], ['y', 'years', 31536000]];
    const tidy = number => Number(number.toPrecision(15));
    function enhance(input) {
        const kind = input.dataset.quantityKind;
        const zeroLabel = zeroLabels[configKey(input)];
        const format = input.dataset.quantityFormat || 'base';
        const units = format === 'retention' ? retentionUnits : kind === 'bytes' ? sizeUnits : durationUnits;
        const baseFactor = input.dataset.baseUnit === 'ms' ? .001 : 1;
        const integer = input.dataset.quantityInteger !== 'false';
        const min = input.getAttribute('min') ?? (kind === 'bytes' ? '0' : null);
        const max = input.getAttribute('max');
        const zeroOrMin = Number(input.dataset.quantityZeroOrMin || 0);
        const id = input.id;
        const label = (input.closest('.plugin-config-field') || document).querySelector(`label[for="${CSS.escape(id)}"]`)?.textContent.trim() || 'Value';
        const wrapper = document.createElement('div');
        wrapper.className = 'config-quantity';
        const amount = document.createElement('input');
        amount.type = 'number'; amount.step = 'any'; amount.id = id; amount.className = 'config-quantity-value';
        amount.required = zeroLabel ? false : input.required;
        amount.setAttribute('aria-label', label);
        const select = document.createElement('select');
        select.className = 'config-quantity-unit'; select.setAttribute('aria-label', `${label} unit`);
        units.forEach(([key, title]) => select.add(new Option(title, key)));
        select.value = input.dataset.quantityPreferredUnit || (format === 'retention' ? 'd' : kind === 'bytes' ? 'MiB' : 's');
        const error = document.createElement('div');
        error.id = `${id}_quantity_error`; error.className = 'config-quantity-error'; error.setAttribute('aria-live', 'polite');
        amount.setAttribute('aria-describedby', `${input.getAttribute('aria-describedby') || ''} ${error.id}`.trim());
        input.before(wrapper); wrapper.append(input, amount, select, error);
        input.type = 'hidden'; input.id = `${id}_canonical`;
        const factor = () => units.find(unit => unit[0] === select.value)[2] / baseFactor;
        function parse(raw) {
            if (format === 'retention') {
                const value = raw.trim().toLowerCase();
                if (['', '0', 'none', 'false', 'no', 'off'].includes(value)) return 0;
                const match = value.match(/^(\d+)\s*(h|hr|hrs|hour|hours|d|day|days|w|week|weeks|mo|month|months|y|yr|yrs|year|years)$/);
                if (!match) return NaN;
                const unit = match[2];
                const seconds = unit.startsWith('h') ? 3600 : unit.startsWith('d') ? 86400 : unit.startsWith('w') ? 604800 : unit.startsWith('mo') ? 2592000 : 31536000;
                return Number(match[1]) * seconds;
            }
            if (raw === '') return null;
            if (format === 'size-text') {
                const match = raw.match(/^(\d+(?:\.\d+)?)\s*([kmgt])?(?:i?b)?$/i);
                return match ? Number(match[1]) * ({k:1024,m:1048576,g:1073741824,t:1099511627776}[match[2]?.toLowerCase()] || 1) : NaN;
            }
            if (format === 'duration-text') {
                const match = raw.match(/^(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)?$/i);
                return match ? Number(match[1]) * (match[2]?.toLowerCase().startsWith('h') ? 3600 : match[2]?.toLowerCase().startsWith('m') ? 60 : 1) : NaN;
            }
            if (format === 'size-suffix') {
                const match = raw.match(/^(\d+)([kmg])?$/i);
                return match ? Number(match[1]) * ({k:1024,m:1048576,g:1073741824}[match[2]?.toLowerCase()] || 1) : NaN;
            }
            return Number(raw);
        }
        function message(text) {
            amount.setCustomValidity(text); error.textContent = text;
            amount.setAttribute('aria-invalid', String(Boolean(text)));
        }
        function problem(raw) {
            if (raw === null) return '';
            if (!Number.isFinite(raw)) return 'Enter a valid number.';
            if (integer && !Number.isSafeInteger(raw)) return `Use a whole number of ${kind === 'bytes' ? 'bytes' : input.dataset.baseUnit === 'ms' ? 'milliseconds' : 'seconds'}.`;
            if (min !== null && raw < Number(min)) return `Minimum: ${tidy(Number(min) / factor())} ${select.selectedOptions[0].text}.`;
            if (input.dataset.exclusiveMinimum !== undefined && raw <= Number(input.dataset.exclusiveMinimum)) return `Use a value greater than ${Number(input.dataset.exclusiveMinimum) / factor()}.`;
            if (max !== null && raw > Number(max)) return `Maximum: ${tidy(Number(max) / factor())} ${select.selectedOptions[0].text}.`;
            if (zeroOrMin && raw !== 0 && raw < zeroOrMin) return `Use 0 or at least ${zeroOrMin} seconds.`;
            if (format === 'retention' && raw !== 0 && (raw < 3600 || raw % 3600)) return 'Use a whole number of hours.';
            return '';
        }
        let slider;
        const rangeMax = format === 'retention' ? 31536000 : ({CRAWL_MAX_SIZE:100e12,SNAPSHOT_MAX_SIZE:10e12,CRAWL_TIMEOUT:604800}[configKey(input)] || Number(input.dataset.quantityRangeMax) || (kind === 'bytes' ? 100 * 1024**3 : 86400 / baseFactor));
        if (input.dataset.quantitySlider && !input.closest('.config-range')) {
            slider = document.createElement('input'); slider.type = 'range'; slider.className = 'config-quantity-slider';
            slider.min = min || '0'; slider.max = max || String(rangeMax); slider.step = format === 'retention' ? '3600' : integer ? '1' : 'any';
            slider.setAttribute('aria-label', `${label} slider`); wrapper.prepend(slider);
            slider.addEventListener('input', () => {
                let raw = Number(slider.value);
                if (zeroOrMin && raw > 0 && raw < zeroOrMin) raw = raw > (parse(input.value) || 0) ? zeroOrMin : 0;
                slider.value = String(raw);
                amount.value = String(tidy(raw / factor()));
                amount.dispatchEvent(new Event('input', {bubbles:true}));
            });
        }
        let lastRaw;
        function refresh(force = false) {
            if (!force && input.value === lastRaw) return;
            lastRaw = input.value;
            const raw = parse(input.value);
            const example = parse(input.getAttribute('placeholder') || '');
            if (example !== null && Number.isFinite(example)) amount.placeholder = String(tidy(example / factor()));
            amount.value = raw === null || !Number.isFinite(raw) || (zeroLabel && raw === 0) ? '' : String(tidy(raw / factor()));
            if (zeroLabel) amount.placeholder = zeroLabel;
            if (min !== null) amount.min = String(tidy(Number(min) / factor()));
            if (max !== null) amount.max = String(tidy(Number(max) / factor()));
            message(problem(raw));
            if (slider && raw !== null && Number.isFinite(raw)) {
                slider.max = max || String(Math.max(rangeMax, raw)); slider.value = String(raw);
                slider.setAttribute('aria-valuetext', raw === 0 && zeroLabel ? zeroLabel : `${amount.value} ${select.selectedOptions[0].text}`);
            }
        }
        // Pick a readable initial unit without rewriting the saved representation.
        const initial = parse(input.value);
        if (initial > 0) {
            const readable = units.filter(unit => unit[0] !== 'ms' && initial * baseFactor >= unit[2] && Number.isInteger(tidy(initial * baseFactor / unit[2]))).at(-1);
            if (readable) select.value = readable[0];
        }
        select.addEventListener('change', () => refresh(true));
        amount.addEventListener('input', () => {
            if (amount.value === '') {
                if (amount.validity.badInput) { message('Enter a valid number.'); return; }
                input.value = zeroLabel ? '0' : ''; message(''); input.dispatchEvent(new Event('input', {bubbles:true})); return;
            }
            const raw = tidy(Number(amount.value) * factor());
            const error = problem(raw);
            if (error) { message(error); return; }
            if (format === 'retention') {
                const unit = retentionUnits.find(unit => unit[0] === select.value);
                input.value = raw === 0 ? '0' : Number.isInteger(raw / unit[2]) ? `${raw / unit[2]}${unit[0]}` : `${raw / 3600}h`;
            } else if (format === 'size-suffix') {
                const suffix = {KiB:'k',MiB:'m',GiB:'g'}[select.value];
                input.value = suffix && Number.isInteger(Number(amount.value)) ? `${amount.value}${suffix}` : String(raw);
            } else input.value = String(raw);
            message(''); input.dispatchEvent(new Event('input', {bubbles:true}));
        });
        amount.addEventListener('change', () => { if (amount.validity.valid) input.dispatchEvent(new Event('change', {bubbles:true})); });
        widgets.set(input, {refresh, amount, parse, select}); refresh();
    }
    function enhanceZero(input) {
        const label = zeroLabels[configKey(input)];
        if (!label || widgets.has(input) || zeroWidgets.has(input)) return;
        // The named input keeps the saved representation; this editable view
        // renders the sentinel as a useful placeholder without submitting it.
        const amount = input.cloneNode(false);
        amount.removeAttribute('name'); amount.removeAttribute('data-config-key');
        amount.classList.remove('plugin-config-input'); amount.classList.add('config-zero-value');
        amount.required = false; amount.placeholder = label;
        input.id += '_canonical'; input.type = 'hidden'; input.after(amount);
        let slider = input.closest('.plugin-config-field')?.querySelector('input[type="range"]');
        if (!slider && input.name === 'max_urls') {
            slider = document.createElement('input'); slider.type = 'range'; slider.min = '0'; slider.max = '1000000'; slider.step = '1';
            slider.className = 'config-quantity-slider'; slider.setAttribute('aria-label', 'URL limit slider');
            input.before(slider);
            slider.addEventListener('input', () => { input.value = slider.value; input.dispatchEvent(new Event('input', {bubbles:true})); });
        }
        const refresh = () => {
            if (slider) { slider.max = String(Math.max(1000000, Number(input.value) || 0)); slider.value = input.value; }
            amount.value = Number(input.value) === 0 ? '' : input.value;
            if (slider) slider.setAttribute('aria-valuetext', Number(input.value) === 0 ? label : input.value);
        };
        amount.addEventListener('input', () => {
            if (amount.validity.badInput) return;
            input.value = amount.value === '' ? '0' : amount.value;
            input.dispatchEvent(new Event('input', {bubbles: true}));
        });
        amount.addEventListener('change', () => input.dispatchEvent(new Event('change', {bubbles: true})));
        zeroWidgets.set(input, {refresh}); refresh();
    }
    window.archiveboxRefreshQuantities = () => {
        document.querySelectorAll('input[data-quantity-kind]').forEach(input => { if (!widgets.has(input)) enhance(input); });
        widgets.forEach(widget => widget.refresh());
        document.querySelectorAll('input[data-config-key][name], #add-form input[name]').forEach(enhanceZero);
        zeroWidgets.forEach(widget => widget.refresh());
    };
    document.addEventListener('input', event => {
        if (widgets.has(event.target)) widgets.get(event.target).refresh();
        if (zeroWidgets.has(event.target)) zeroWidgets.get(event.target).refresh();
    });
    document.addEventListener('change', event => { if (!event.target.closest('.config-quantity')) window.archiveboxRefreshQuantities(); });
    document.addEventListener('DOMContentLoaded', window.archiveboxRefreshQuantities);
    // Django admin uses novalidate; quantity widgets still validate their own units before submission.
    document.addEventListener('submit', event => {
        for (const [input, widget] of widgets) {
            if (input.form === event.target && !widget.amount.checkValidity()) {
                event.preventDefault(); widget.amount.reportValidity(); break;
            }
        }
    }, true);
})();
