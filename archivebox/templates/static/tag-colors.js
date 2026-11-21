window.applyArchiveBoxTagColor = function (element, name) {
    // Match Python str.strip() and iterate Unicode code points, not UTF-16 units.
    const trimmed = String(name || '').replace(/^[\p{White_Space}\x1c-\x1f]+|[\p{White_Space}\x1c-\x1f]+$/gu, '');
    let hue = 0;
    for (const char of trimmed.toLowerCase()) {
        hue = (hue * 31 + char.codePointAt(0)) % 360;
    }
    element.style.setProperty('--tag-bg', `hsl(${hue}, 70%, 92%)`);
    element.style.setProperty('--tag-border', `hsl(${hue}, 60%, 82%)`);
    element.style.setProperty('--tag-fg', `hsl(${hue}, 35%, 28%)`);
};
