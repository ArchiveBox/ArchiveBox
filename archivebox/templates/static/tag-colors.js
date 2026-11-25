function archiveBoxTagHashHue(text) {
    let hue = 0;
    for (const char of text) hue = (hue * 31 + char.codePointAt(0)) % 360;
    return hue;
}

window.applyArchiveBoxTagColor = function (element, name) {
    // Match Python str.strip() and iterate Unicode code points, not UTF-16 units.
    const trimmed = String(name || '').replace(/^[\p{White_Space}\x1c-\x1f]+|[\p{White_Space}\x1c-\x1f]+$/gu, '');
    const normalized = trimmed.toLowerCase();
    let hue = archiveBoxTagHashHue(normalized);
    const topics = new Set();
    for (const word of normalized.match(/[\p{L}\p{N}]+/gu) || []) {
        if (Object.hasOwn(archiveBoxTagColorHues, word)) topics.add(archiveBoxTagColorHues[word]);
    }
    if (topics.size === 1) hue = (topics.values().next().value + hue % 17 - 8 + 360) % 360;
    else if (!topics.size) {
        const namespace = normalized.match(/^([a-z]{3,})[-_:][a-z]{2}/);
        if (namespace) hue = (archiveBoxTagHashHue(namespace[1]) + hue % 17 - 8 + 360) % 360;
    }
    element.style.setProperty('--tag-bg', `hsl(${hue}, 70%, 92%)`);
    element.style.setProperty('--tag-border', `hsl(${hue}, 60%, 82%)`);
    element.style.setProperty('--tag-fg', `hsl(${hue}, 35%, 28%)`);
};
