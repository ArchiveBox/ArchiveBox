/* Form tag editors synchronize through their hidden field and its change event. */
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.tag-editor-container').forEach(container => {
        const input = container.querySelector('.tag-inline-input');
        const hidden = container.querySelector('input[type="hidden"]');
        const pills = container.querySelector('.tag-pills');
        const datalist = container.querySelector('datalist');
        let tags = JSON.parse(document.getElementById(container.dataset.tagsId).textContent);
        let autocompleteTimeout;

        function normalize(value) {
            const seen = new Set();
            return (Array.isArray(value) ? value : String(value || '').split(','))
                .map(tag => String(tag || '').trim())
                .filter(tag => {
                    const key = tag.toLowerCase();
                    if (!tag || seen.has(key)) return false;
                    seen.add(key);
                    return true;
                })
                .sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
        }

        function render() {
            pills.replaceChildren(...tags.map(tag => {
                const pill = document.createElement('span');
                pill.className = 'tag-pill';
                pill.dataset.tag = tag;
                ArchiveBoxUI.styleTag(pill, tag);
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'tag-remove-btn';
                remove.dataset.tagName = tag;
                remove.textContent = '×';
                pill.append(document.createTextNode(tag), remove);
                return pill;
            }));
        }

        function update(value) {
            tags = normalize(value);
            render();
            hidden.value = tags.join(',');
            for (const type of ['input', 'change']) hidden.dispatchEvent(new Event(type, {bubbles: true}));
        }

        function sync() {
            tags = normalize(hidden.value);
            render();
        }
        hidden.addEventListener('change', sync);
        hidden.addEventListener('archivebox:sync-tags', sync);
        container.addEventListener('click', event => {
            const remove = event.target.closest('.tag-remove-btn');
            if (remove) update(tags.filter(tag => tag.toLowerCase() !== remove.dataset.tagName.toLowerCase()));
            else input.focus();
        });
        input.addEventListener('keydown', event => {
            const value = input.value.trim();
            if (['Enter', ' ', 'Spacebar', ','].includes(event.key)) {
                event.preventDefault();
                event.stopPropagation();
                const existing = new Set(tags.map(tag => tag.toLowerCase()));
                const added = normalize(value.split(/[\s,]+/)).filter(tag => !existing.has(tag.toLowerCase()));
                update([...tags, ...added]);
                input.value = '';
                for (const name of added) {
                    fetch(ArchiveBoxUI.apiUrl('/api/v1/core/tags/create/'), {
                        method: 'POST', headers: ArchiveBoxUI.apiHeaders(), body: JSON.stringify({name}),
                    }).catch(error => console.log('Tag creation note:', error));
                }
            } else if (event.key === 'Backspace' && !value) {
                update(tags.slice(0, -1));
            }
        });
        input.addEventListener('input', () => {
            clearTimeout(autocompleteTimeout);
            const query = input.value;
            autocompleteTimeout = setTimeout(async () => {
                datalist.replaceChildren();
                if (!query) return;
                try {
                    const response = await fetch(ArchiveBoxUI.apiUrl('/api/v1/core/tags/autocomplete/?q=' + encodeURIComponent(query)));
                    const data = await response.json();
                    // Ignore a response for a query the user has already replaced.
                    if (query !== input.value) return;
                    datalist.replaceChildren(...(data.tags || []).map(tag => {
                        const option = document.createElement('option');
                        option.value = tag.name;
                        return option;
                    }));
                } catch (error) {
                    console.log('Autocomplete error:', error);
                }
            }, 150);
        });
        tags = normalize(tags);
        render();
    });
});
