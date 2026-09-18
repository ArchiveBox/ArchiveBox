/* Shared browser primitives for ArchiveBox forms, tags, and progress controls. */
window.ArchiveBoxUI = {
    apiKey() {
        return (window.ARCHIVEBOX_API_KEY || '').trim();
    },
    apiUrl(path) {
        const key = ArchiveBoxUI.apiKey();
        return key ? path + (path.includes('?') ? '&' : '?') + 'api_key=' + encodeURIComponent(key) : path;
    },
    csrfToken() {
        const input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (input?.value) return input.value;
        const cookie = document.cookie.split(';').map(value => value.trim()).find(value => value.startsWith('csrftoken='));
        return cookie ? decodeURIComponent(cookie.slice('csrftoken='.length)) : '';
    },
    apiHeaders(json = true) {
        const headers = json ? {'Content-Type': 'application/json'} : {};
        const key = ArchiveBoxUI.apiKey();
        const csrf = ArchiveBoxUI.csrfToken();
        if (key) headers['X-ArchiveBox-API-Key'] = key;
        if (csrf) headers['X-CSRFToken'] = csrf;
        return headers;
    },
    async apiFetch(path, options = {}) {
        const response = await fetch(ArchiveBoxUI.apiUrl(path), {
            credentials: 'same-origin',
            ...options,
            headers: {...ArchiveBoxUI.apiHeaders(Boolean(options.body)), ...options.headers},
        });
        if (!response.ok) {
            let message = await response.text();
            try {
                const data = JSON.parse(message);
                message = data.detail || data.message || data.error || message;
            } catch (_) {
                // Non-JSON errors keep the server's response text.
            }
            throw new Error(message || `Request failed (${response.status})`);
        }
        return response;
    },
    escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"'`]/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;',
        }[char]));
    },
    styleTag(element, name) {
        let hue = 0;
        for (const char of String(name || '').toLowerCase()) hue = (hue * 31 + char.charCodeAt(0)) % 360;
        element.style.setProperty('--tag-bg', `hsl(${hue}, 70%, 92%)`);
        element.style.setProperty('--tag-border', `hsl(${hue}, 60%, 82%)`);
        element.style.setProperty('--tag-fg', `hsl(${hue}, 35%, 28%)`);
    },
};
