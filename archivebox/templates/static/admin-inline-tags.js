(function() {
    function getApiKey() {
        return (window.ARCHIVEBOX_API_KEY || '').trim();
    }

    function buildApiUrl(path) {
        var apiKey = getApiKey();
        if (!apiKey) return path;
        var sep = path.indexOf('?') !== -1 ? '&' : '?';
        return path + sep + 'api_key=' + encodeURIComponent(apiKey);
    }

    function getCSRFToken() {
        var cookies = document.cookie.split(';');
        for (var i = 0; i < cookies.length; i++) {
            var cookie = cookies[i].trim();
            if (cookie.startsWith('csrftoken=')) {
                return cookie.substring('csrftoken='.length);
            }
        }
        var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
        return input ? input.value : '';
    }

    function buildApiHeaders() {
        var headers = {
            'Content-Type': 'application/json'
        };
        var apiKey = getApiKey();
        if (apiKey) headers['X-ArchiveBox-API-Key'] = apiKey;
        var csrfToken = getCSRFToken();
        if (csrfToken) headers['X-CSRFToken'] = csrfToken;
        return headers;
    }

    function insertTag(el, id, name) {
        const container = el.querySelector('.tag-pills-inline');
        if (!container || container.querySelector(`[data-tag-id="${CSS.escape(String(id))}"]`)) return;
        const pill = document.createElement('span');
        pill.className = 'tag-pill';
        pill.dataset.tag = name;
        pill.dataset.tagId = id;
        window.applyArchiveBoxTagColor(pill, name);

        const link = document.createElement('a');
        link.href = '/admin/core/snapshot/?tags__id__exact=' + id;
        link.className = 'tag-link';
        link.textContent = link.title = name;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'tag-remove-btn';
        remove.textContent = '×';
        pill.append(link, remove);

        // Read the live list when the save completes so overlapping edits
        // preserve each other's pills and keep untouched links focused.
        const next = Array.from(container.children).find(existing =>
            name.toLowerCase().localeCompare(existing.dataset.tag.toLowerCase()) < 0
        );
        container.insertBefore(pill, next || null);
    }

    function addTag(el, tagName) {
        tagName = String(tagName || '').trim();
        if (!tagName) return;

        var exists = Array.from(el.querySelectorAll('.tag-pill')).some(function(pill) {
            return pill.dataset.tag.toLowerCase() === tagName.toLowerCase();
        });
        if (exists) return;

        var snapshotId = el.dataset.snapshotId || '';
        fetch(buildApiUrl('/api/v1/core/tags/add-to-snapshot/'), {
            method: 'POST',
            headers: buildApiHeaders(),
            body: JSON.stringify({
                snapshot_id: snapshotId,
                tag_name: tagName
            })
        })
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.success) {
                insertTag(el, data.tag_id, data.tag_name);
            }
        })
        .catch(function(err) {
            console.error('Error adding tag:', err);
        });
    }

    function removeTag(el, tagId) {
        var snapshotId = el.dataset.snapshotId || '';
        fetch(buildApiUrl('/api/v1/core/tags/remove-from-snapshot/'), {
            method: 'POST',
            headers: buildApiHeaders(),
            body: JSON.stringify({
                snapshot_id: snapshotId,
                tag_id: tagId
            })
        })
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.success) {
                el.querySelector(`.tag-pill[data-tag-id="${CSS.escape(String(tagId))}"]`)?.remove();
            }
        })
        .catch(function(err) {
            console.error('Error removing tag:', err);
        });
    }

    function handleContainerClick(event) {
        var target = event.target;
        var container = target.closest('.tag-editor-inline');
        if (!container) return;

        if (target.classList.contains('tag-remove-btn')) {
            event.stopPropagation();
            event.preventDefault();
            var tagId = Number(target.closest('.tag-pill').dataset.tagId);
            if (tagId) removeTag(container, tagId);
            return;
        }

        if (!target.classList.contains('tag-link')) {
            var input = container.querySelector('input.tag-inline-input-sm');
            if (input) input.focus();
        }
    }

    function handleInputKeydown(event) {
        var input = event.target;
        if (!input || !input.matches('input.tag-inline-input-sm')) return;
        var container = input.closest('.tag-editor-inline');
        if (!container) return;

        var value = input.value.trim();
        if (event.key === 'Enter' || event.keyCode === 13 || event.key === ' ' || event.key === ',') {
            event.preventDefault();
            if (value) {
                value.split(',').forEach(function(tag) { addTag(container, tag.trim()); });
                input.value = '';
            }
        }
    }

    function handleInputFocus(event) {
        var input = event.target;
        if (!input || !input.matches('input.tag-inline-input-sm')) return;
        input.placeholder = 'add tag...';
    }

    function handleInputBlur(event) {
        var input = event.target;
        if (!input || !input.matches('input.tag-inline-input-sm')) return;
        input.placeholder = '+';
    }

    function init() {
        document.addEventListener('click', handleContainerClick);
        document.addEventListener('keydown', handleInputKeydown);
        document.addEventListener('focusin', handleInputFocus);
        document.addEventListener('focusout', handleInputBlur);
        document.addEventListener('archivebox:tag-deleted', function(event) {
            const id = String(event.detail);
            document.querySelectorAll(`.tag-editor-inline .tag-pill[data-tag-id="${CSS.escape(id)}"]`).forEach(pill => {
                pill.remove();
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
