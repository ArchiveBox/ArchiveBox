// Parse into a template so discarded result previews never start loading.
function searchFragment(html) {
    const template = document.createElement('template');
    template.innerHTML = html;
    template.content.querySelectorAll('script').forEach(script => script.remove());
    return template.content;
}

function syncSearchRows(current, incoming, retained = 0) {
    // Keep live browsing contexts attached. Even removing and reinserting the
    // same iframe node starts a new navigation in its embedded document.
    const next = Array.from(incoming.children);
    const keep = new Set(next.map(row => row.dataset.snapshotId).filter(Boolean));
    const existing = new Map();
    for (const row of Array.from(current.children).slice(retained)) {
        const id = row.dataset.snapshotId;
        if (keep.has(id)) existing.set(id, row);
        else row.remove();
    }
    const added = [];
    const tail = document.createDocumentFragment();
    let cursor = current.children[retained] || null;
    for (const fresh of next) {
        const row = existing.get(fresh.dataset.snapshotId);
        if (!row) {
            if (cursor) current.insertBefore(fresh, cursor);
            else tail.append(fresh);
            added.push(fresh);
            continue;
        }
        if (row !== cursor) {
            if (current.moveBefore) current.moveBefore(row, cursor);
            else current.insertBefore(row, cursor);
        }
        // Rank can change when a provisional page settles. Keep client state
        // such as selection and expanded tags on the original element.
        const rank = Array.from(fresh.classList).find(name => name.startsWith('search-rank-'));
        for (const name of Array.from(row.classList)) {
            if (name.startsWith('search-rank-') && name !== rank) row.classList.remove(name);
        }
        if (rank && !row.classList.contains(rank)) row.classList.add(rank);
        cursor = row.nextElementSibling;
    }
    // In the usual append-only wave this is the only write to the live list.
    if (tail.childElementCount) current.append(tail);
    return added;
}

function searchProgress(pageSize) {
    const bar = document.createElement('progress');
    bar.max = pageSize;
    bar.value = 0;
    bar.setAttribute('aria-label', 'Matches found for first page');
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const use = document.createElementNS(icon.namespaceURI, 'use');
    icon.setAttribute('aria-hidden', 'true');
    icon.append(use);
    const label = document.createTextNode('Request');
    const numbers = document.createTextNode('');
    const clock = document.createElement('span');
    clock.className = 'search-phase-time';
    // Announce phase changes, without reading the ticking clock every second.
    clock.setAttribute('aria-live', 'off');
    const phases = {
        planning: ['Plan', 'search'], sql: ['SQL', 'database'], python: ['Python', 'type'],
        links: ['FS · links', 'link'], files: ['FS · files', 'file'],
        provider: ['Index', 'database'], queue: ['Worker queue', 'puzzle'],
    };
    let state, verifying = false, received = performance.now(), timer;
    function tick() {
        const delta = performance.now() - received;
        const seconds = Math.floor(((state?.ms || 0) + delta) / 1000);
        let text = state ? seconds + 's/' + (state.limit == null ? '∞' : Math.round(state.limit) + 's') : seconds + 's';
        if (state?.idle != null) text += ' · idle ' + Math.floor((state.idle + delta) / 1000) + '/' + state.stall + 's';
        if (text !== clock.textContent) clock.textContent = text;
    }
    return {
        show(status) {
            if (bar.parentNode !== status) status.replaceChildren(bar, icon, label, numbers, clock);
            status.hidden = false;
            if (!timer) { tick(); timer = setInterval(tick, 1000); }
        },
        stop() { clearInterval(timer); timer = null; },
        count(value) {
            if (!verifying) bar.value = Math.min(value, pageSize);
        },
        work(line) {
            if (!line.startsWith('work ')) return false;
            state = JSON.parse(line.slice(5));
            received = performance.now();
            const [name, symbol] = phases[state.phase] || phases.python;
            const sprite = document.querySelector('.abx-search-field')?.dataset.icons;
            if (sprite) use.setAttribute('href', sprite + '#' + symbol);
            label.data = state.provider || name;
            numbers.data = state.checked || state.total != null
                ? ' · ' + state.checked.toLocaleString() + (state.total == null ? '' : '/' + state.total.toLocaleString()) + ' checked'
                : '';
            clock.title = state.limit == null ? 'Phase elapsed · no search-imposed deadline' : 'Phase elapsed / timeout';
            if (state.idle != null) clock.title += ' · idle since last worker output / stall timeout';
            if (!verifying && (state.checked || state.total != null || ['links', 'files'].includes(state.phase))) {
                verifying = true;
                // Without a denominator, the checked count advances and the
                // track stays still. A native indeterminate bar would loop.
                bar.value = 0;
                bar.setAttribute('aria-label', 'Snapshots checked');
                bar.setAttribute('aria-valuetext', 'Total unknown');
            }
            if (state.total > 0) {
                bar.max = state.total;
                bar.value = state.checked;
                bar.removeAttribute('aria-valuetext');
            }
            tick();
            return true;
        },
        finishing() { bar.value = bar.max; },
    };
}
// Consume the first real row with the same renderer as a later HTTP fragment.
function firstSearchFragment(line) {
    if (!line.startsWith('first ')) return null;
    const {html, headers, count} = JSON.parse(line.slice(6));
    return {response: new Response(html, {headers}), count};
}
