(() => {
    document.addEventListener('click', (event) => {
        const button = event.target.closest('button[data-schedule-preset]');
        if (!button) return;
        const input = button.closest('.schedule-presets')?.querySelector('input');
        if (!input || input.disabled || input.readOnly) return;
        input.value = button.dataset.schedulePreset;
        input.dispatchEvent(new Event('input', {bubbles: true}));
        input.dispatchEvent(new Event('change', {bubbles: true}));
        input.focus();
    });
})();
