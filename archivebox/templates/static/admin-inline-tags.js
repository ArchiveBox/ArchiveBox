(function() {
    function parseTags(el) {
        if (el._tagData) return el._tagData;
        var raw = el.dataset.tags || '[]';
        try {
            el._tagData = JSON.parse(raw);
        } catch (e) {
            el._tagData = [];
        }
        return el._tagData;
    }

    function setTags(el, tags) {
        el._tagData = tags;
        el.dataset.tags = JSON.stringify(tags);
    }

    function rebuildPills(el) {
        var tags = parseTags(el);
        var container = el.querySelector('.tag-pills-inline');
        if (!container) return;
        container.innerHTML = '';
        tags.forEach(function(td) {
            var pill = document.createElement('span');
            pill.className = 'tag-pill';
            pill.setAttribute('data-tag', td.name);
            pill.setAttribute('data-tag-id', td.id);
            ArchiveBoxUI.styleTag(pill, td.name);

            var link = document.createElement('a');
            link.href = '/admin/core/snapshot/?tags__id__exact=' + td.id;
            link.className = 'tag-link';
            link.textContent = td.name;
            pill.appendChild(link);

            var removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'tag-remove-btn';
            removeBtn.setAttribute('data-tag-id', td.id);
            removeBtn.setAttribute('data-tag-name', td.name);
            removeBtn.innerHTML = '&times;';
            pill.appendChild(removeBtn);

            container.appendChild(pill);
        });
    }

    function addTag(el, tagName) {
        tagName = String(tagName || '').trim();
        if (!tagName) return;

        var tags = parseTags(el);
        var exists = tags.some(function(t) {
            return t.name.toLowerCase() === tagName.toLowerCase();
        });
        if (exists) return;

        var snapshotId = el.dataset.snapshotId || '';
        ArchiveBoxUI.apiFetch('/api/v1/core/tags/add-to-snapshot/', {
            method: 'POST',
            body: JSON.stringify({
                snapshot_id: snapshotId,
                tag_name: tagName
            })
        })
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.success) {
                tags.push({ id: data.tag_id, name: data.tag_name });
                tags.sort(function(a, b) { return a.name.toLowerCase().localeCompare(b.name.toLowerCase()); });
                setTags(el, tags);
                rebuildPills(el);
            }
        })
        .catch(function(err) {
            console.error('Error adding tag:', err);
        });
    }

    function removeTag(el, tagId) {
        var snapshotId = el.dataset.snapshotId || '';
        ArchiveBoxUI.apiFetch('/api/v1/core/tags/remove-from-snapshot/', {
            method: 'POST',
            body: JSON.stringify({
                snapshot_id: snapshotId,
                tag_id: tagId
            })
        })
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.success) {
                var tags = parseTags(el).filter(function(t) { return t.id !== tagId; });
                setTags(el, tags);
                rebuildPills(el);
            }
        })
        .catch(function(err) {
            console.error('Error removing tag:', err);
        });
    }

    var autocompleteTimers = new WeakMap();

    function fetchAutocomplete(el, query, datalist) {
        if (!datalist) return;
        var existing = autocompleteTimers.get(el);
        if (existing) window.clearTimeout(existing);

        var timer = window.setTimeout(function() {
            if (!query || query.length < 1) {
                datalist.innerHTML = '';
                return;
            }

            ArchiveBoxUI.apiFetch('/api/v1/core/tags/autocomplete/?q=' + encodeURIComponent(query))
                .then(function(response) { return response.json(); })
                .then(function(data) {
                    datalist.innerHTML = '';
                    (data.tags || []).forEach(function(tag) {
                        var option = document.createElement('option');
                        option.value = tag.name;
                        datalist.appendChild(option);
                    });
                })
                .catch(function(err) {
                    console.log('Autocomplete error:', err);
                });
        }, 150);

        autocompleteTimers.set(el, timer);
    }

    function handleContainerClick(event) {
        var target = event.target;
        var container = target.closest('.tag-editor-inline');
        if (!container) return;

        if (target.classList.contains('tag-remove-btn')) {
            event.stopPropagation();
            event.preventDefault();
            var tagId = parseInt(target.getAttribute('data-tag-id'), 10);
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

    function handleInputEvent(event) {
        var input = event.target;
        if (!input || !input.matches('input.tag-inline-input-sm')) return;
        var container = input.closest('.tag-editor-inline');
        if (!container) return;
        var datalist = container.querySelector('datalist');
        fetchAutocomplete(container, input.value, datalist);
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
        document.addEventListener('input', handleInputEvent);
        document.addEventListener('focusin', handleInputFocus);
        document.addEventListener('focusout', handleInputBlur);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
