document.addEventListener('DOMContentLoaded', function () {
    const shell = document.getElementById('abx-tag-admin');
    if (!shell) return;

    const initialCards = JSON.parse(document.getElementById('abx-tag-cards-data').textContent || '[]');
    const searchUrl = shell.dataset.searchUrl;
    const createUrl = shell.dataset.createUrl;
    const searchInput = document.getElementById('tag-live-search');
    const sortSelect = document.getElementById('tag-sort-select');
    const createdBySelect = document.getElementById('tag-created-by-select');
    const yearSelect = document.getElementById('tag-year-select');
    const createForm = document.getElementById('tag-create-form');
    const createInput = document.getElementById('tag-create-name');
    const grid = document.getElementById('tag-card-grid');
    const queryLabel = document.getElementById('tag-query-label');
    const toast = document.getElementById('tag-toast');
    let searchTimeout = null;


    function setToast(message, tone) {
        toast.textContent = message;
        toast.className = 'tag-toast is-visible ' + (tone === 'error' ? 'is-error' : 'is-success');
        window.clearTimeout(setToast._timer);
        setToast._timer = window.setTimeout(function () {
            toast.className = 'tag-toast';
            toast.textContent = '';
        }, 2600);
    }

    function getCurrentState(overrides) {
        const next = overrides || {};
        return {
            query: typeof next.query === 'string' ? next.query.trim() : (searchInput?.value || '').trim(),
            sort: typeof next.sort === 'string' ? next.sort : (sortSelect?.value || 'created_desc'),
            created_by: typeof next.created_by === 'string' ? next.created_by : (createdBySelect?.value || ''),
            year: typeof next.year === 'string' ? next.year : (yearSelect?.value || ''),
            has_snapshots: typeof next.has_snapshots === 'string' ? next.has_snapshots : (shell.dataset.initialHasSnapshots || 'all'),
        };
    }

    function syncSearchState(state) {
        if (searchInput) searchInput.value = state.query;
        if (sortSelect) sortSelect.value = state.sort;
        if (createdBySelect) createdBySelect.value = state.created_by;
        if (yearSelect) yearSelect.value = state.year;
    }

    function syncLocation(state) {
        const url = new URL(window.location.href);
        const params = {
            q: state.query,
            sort: state.sort === 'created_desc' ? '' : state.sort,
            created_by: state.created_by,
            year: state.year,
            has_snapshots: state.has_snapshots === 'all' ? '' : state.has_snapshots,
        };
        for (const [key, value] of Object.entries(params)) {
            if (value) url.searchParams.set(key, value);
            else url.searchParams.delete(key);
        }

        window.history.replaceState({}, '', url.toString());
    }

    function setMeta(state, count) {
        const baseLabel = state.query ? '"' + state.query + '"' : 'All tags';
        queryLabel.textContent = baseLabel + ' · ' + count + ' shown';
    }

    function renderCards(nextCards, state) {
        const cards = Array.isArray(nextCards) ? nextCards : [];
        setMeta(state || getCurrentState(), cards.length);

        if (!cards.length) {
            grid.innerHTML = '<div class="tag-empty-state">No tags.</div>';
            return;
        }

        const template = document.getElementById('tag-card-template');
        grid.replaceChildren(...cards.map(card => {
            const element = template.content.firstElementChild.cloneNode(true);
            for (const key of ['id', 'slug', 'filter_url', 'rename_url', 'delete_url', 'export_urls_url', 'export_jsonl_url']) {
                element.setAttribute('data-' + key.replaceAll('_', '-'), card[key] ?? '');
            }
            element.querySelector('strong').textContent = card.name;
            const input = element.querySelector('input');
            input.value = card.name;
            input.setAttribute('aria-label', 'Rename tag ' + card.name);
            const count = element.querySelector('.tag-card__count');
            count.textContent = card.num_snapshots;
            count.href = card.filter_url;
            return element;
        }));
    }

    async function fetchCards(state) {
        const params = new URLSearchParams();
        if (state.query) params.set('q', state.query);
        if (state.sort) params.set('sort', state.sort);
        if (state.created_by) params.set('created_by', state.created_by);
        if (state.year) params.set('year', state.year);
        if (state.has_snapshots) params.set('has_snapshots', state.has_snapshots);
        const response = await ArchiveBoxUI.apiFetch(searchUrl + '?' + params.toString());
        const payload = await response.json();
        return {
            tags: payload.tags || [],
            state: {
                query: state.query,
                sort: payload.sort || state.sort,
                created_by: payload.created_by || '',
                year: payload.year || '',
                has_snapshots: payload.has_snapshots || state.has_snapshots,
            },
        };
    }

    async function refreshCards(overrides) {
        const requestedState = getCurrentState(overrides);
        const result = await fetchCards(requestedState);
        syncSearchState(result.state);
        renderCards(result.tags, result.state);
        syncLocation(result.state);
        return result.tags;
    }

    async function submitJson(url, method, payload) {
        const response = await ArchiveBoxUI.apiFetch(url, {method, body: JSON.stringify(payload || {})});
        if (response.status === 204) return {};
        return response.json();
    }

    async function copyTextFromUrl(url) {
        const response = await ArchiveBoxUI.apiFetch(url);
        const text = await response.text();
        await copyTextToClipboard(text);
        return text;
    }

    async function copyTextToClipboard(text) {
        if (navigator.clipboard && window.isSecureContext) {
            try {
                await navigator.clipboard.writeText(text);
                return;
            } catch (_error) {
            }
        }

        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', '');
        textarea.style.position = 'fixed';
        textarea.style.top = '-9999px';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();

        const copied = document.execCommand('copy');
        document.body.removeChild(textarea);
        if (!copied) {
            throw new Error('Clipboard write failed');
        }
    }

    function getDownloadFilename(response, fallbackFilename) {
        const disposition = response.headers.get('Content-Disposition') || '';
        const utf8Match = disposition.match(/filename\\*=UTF-8''([^;]+)/i);
        if (utf8Match && utf8Match[1]) {
            return decodeURIComponent(utf8Match[1]);
        }

        const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
        if (filenameMatch && filenameMatch[1]) {
            return filenameMatch[1];
        }

        return fallbackFilename;
    }

    async function downloadFileFromUrl(url, fallbackFilename) {
        const response = await ArchiveBoxUI.apiFetch(url);
        const blob = await response.blob();
        const downloadUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = getDownloadFilename(response, fallbackFilename);
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(function () {
            URL.revokeObjectURL(downloadUrl);
        }, 1000);
    }

    createForm?.addEventListener('submit', async function (event) {
        event.preventDefault();
        const name = (createInput.value || '').trim();
        if (!name) {
            setToast('Enter a tag name first.', 'error');
            createInput.focus();
            return;
        }

        const button = createForm.querySelector('button[type="submit"]');
        button.disabled = true;
        try {
            const result = await submitJson(createUrl, 'POST', { name: name });
            createInput.value = '';
            await refreshCards({ query: result.tag_name || name });
            setToast(result.created ? 'Tag created.' : 'Existing tag loaded.', 'success');
        } catch (error) {
            setToast(error.message || 'Failed to create tag.', 'error');
        } finally {
            button.disabled = false;
        }
    });

    searchInput?.addEventListener('input', function () {
        window.clearTimeout(searchTimeout);
        searchTimeout = window.setTimeout(async function () {
            try {
                await refreshCards();
            } catch (error) {
                setToast(error.message || 'Failed to search tags.', 'error');
            }
        }, 150);
    });

    [sortSelect, createdBySelect, yearSelect].forEach(function (field) {
        field?.addEventListener('change', async function () {
            try {
                await refreshCards();
            } catch (error) {
                setToast(error.message || 'Failed to update tag filters.', 'error');
            }
        });
    });

    const cardActions = {
        edit(card) {
            card.classList.add('is-editing');
            const input = card.querySelector('.tag-card__rename input');
            input.focus();
            input.select();
        },
        'cancel-edit'(card) {
            card.classList.remove('is-editing');
        },
        async 'save-edit'(card) {
            const input = card.querySelector('.tag-card__rename input');
            const name = input.value.trim();
            if (!name) {
                input.focus();
                throw new Error('Tag name is required.');
            }
            await submitJson(card.dataset.renameUrl, 'POST', {name});
            await refreshCards();
            setToast('Tag renamed.', 'success');
        },
        async delete(card) {
            const name = card.querySelector('.tag-card__display strong').textContent || 'this tag';
            if (!window.confirm('Delete "' + name + '"? This only removes the tag and its tag links.')) return;
            await ArchiveBoxUI.apiFetch(card.dataset.deleteUrl, {method: 'DELETE'});
            await refreshCards();
            setToast('Tag deleted.', 'success');
        },
        'copy-urls'(card) {
            return copyTextFromUrl(card.dataset.exportUrlsUrl);
        },
        'download-jsonl'(card) {
            return downloadFileFromUrl(card.dataset.exportJsonlUrl, 'tag-' + (card.dataset.slug || 'tag') + '-snapshots.jsonl');
        },
    };

    grid.addEventListener('click', async event => {
        // Editing a name must not navigate to the card's snapshot list.
        if (event.target.closest('input, a')) return;
        const card = event.target.closest('.tag-card');
        if (!card) return;
        const button = event.target.closest('[data-action]');
        if (!button) {
            window.location.href = card.dataset.filterUrl;
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        const action = cardActions[button.dataset.action];
        if (!action) return;
        button.disabled = true;
        try {
            await action(card);
        } catch (error) {
            setToast(error.message || 'Tag action failed.', 'error');
        } finally {
            button.disabled = false;
        }
    });

    grid.addEventListener('keydown', function (event) {
        if (event.key !== 'Enter') return;
        const input = event.target.closest('.tag-card__rename input');
        if (!input) return;
        event.preventDefault();
        const saveButton = input.closest('.tag-card__rename')?.querySelector('[data-action="save-edit"]');
        saveButton?.click();
    });

    const initialState = getCurrentState();
    renderCards(initialCards, initialState);
    syncLocation(initialState);
});
